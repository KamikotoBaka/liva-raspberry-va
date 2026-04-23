from fastapi import FastAPI
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Response
from fastapi import UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from threading import Lock
from threading import Thread
from uuid import uuid4
import shutil
import tempfile

from dispatcher import CommandDispatcher
from ai_router import AIRouter
from custom_commands_store import load_custom_commands
from custom_commands_store import save_custom_commands
from error_store import ErrorStore
from hue_lights_service import set_room_lights
from hue_lights_service import set_multimedia_room_lights
from settings import AssistantSettingsRequest
from settings import AssistantSettingsResponse
from settings import SettingsService
from tts.piper_tts import PiperTTS
from wakeword.openwakeword_service import OpenWakeWordService
from voice_auth import can_execute
from voice_auth import identify_speaker_from_file
from voice_auth import _get_encoder_and_preprocess, _load_profiles

class ProcessRequest(BaseModel):
	text: str


class ProcessResponse(BaseModel):
	sttText: str
	commandText: str
	ttsText: str
	intent: str
	errorEventId: str | None = None
	errorTimestamp: str | None = None


class ChatTurnRequest(BaseModel):
	text: str


class ChatTurnResponse(ProcessResponse):
	route: str
	routeReason: str
	intentGuess: str | None = None


class ErrorEvent(BaseModel):
	id: str
	timestamp: str
	device: str
	reason: str
	intent: str


class WakewordDetectRequest(BaseModel):
	samples: list[float]
	sampleRate: int


class WakewordDetectResponse(BaseModel):
	available: bool
	detected: bool
	score: float
	threshold: float
	wakeword: str
	reason: str


class EffectiveSettingsResponse(BaseModel):
	theme: str
	speechModel: str
	computeDevice: str
	responseMode: str
	voiceVolume: int
	activeSttModel: str
	activeSttDevice: str


class SecureProcessResponse(ProcessResponse):
	speakerName: str
	speakerRole: str
	speakerConfidence: float
	accessGranted: bool
	denialReason: str | None = None
	authToken: str | None = None
	expiresInSeconds: int = 0


class SecureTextProcessRequest(BaseModel):
	text: str
	authToken: str


class VoiceAuthResponse(BaseModel):
	speakerName: str
	speakerRole: str
	speakerConfidence: float
	accessGranted: bool
	authToken: str | None = None
	expiresInSeconds: int = 0
	reason: str | None = None


class CustomCommandPayload(BaseModel):
	trigger: str
	category: str = "General"
	actionType: str = "REST"
	actionTarget: str
	responseTemplate: str = "Command executed."


app = FastAPI(title="Voice Assistant Backend")
app.add_middleware(
	CORSMiddleware,
	allow_origins=[
		"http://localhost:5173",
		"http://127.0.0.1:5173",
		"http://localhost:5174",
		"http://127.0.0.1:5174",
		"http://192.168.0.179:5173",
	],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

error_store = ErrorStore()
dispatcher = CommandDispatcher(error_store=error_store)
tts = PiperTTS()
wakeword_service = OpenWakeWordService()
settings_service = SettingsService()

runtime_settings = settings_service.load()
stt = settings_service.create_stt(runtime_settings)
stt_preload_lock = Lock()
auth_sessions: dict[str, dict] = {}
VOICE_AUTH_SESSION_SECONDS = 120


def _get_runtime_settings() -> dict:
	return runtime_settings


ai_router = AIRouter(dispatcher=dispatcher, settings_getter=_get_runtime_settings)


def _preload_stt_in_background(active_stt) -> None:
	if not hasattr(active_stt, "preload"):
		return

	def _runner() -> None:
		with stt_preload_lock:
			try:
				active_stt.preload()
			except RuntimeError:
				# Keep backend running even when faster-whisper is not installed yet.
				pass

	Thread(target=_runner, daemon=True).start()


_preload_stt_in_background(stt)
@app.on_event("startup")  
async def startup_event():
	try:
		_get_encoder_and_preprocess()
		_load_profiles()
	except RuntimeError:
		# Keep backend startup alive even when optional voice-auth deps are missing.
		pass

def _build_process_response(stt_text: str) -> ProcessResponse:
	dispatch_result = dispatcher.dispatch(stt_text)

	tts_text = dispatch_result["tts_text"]
	_ = tts.command_preview(tts_text)

	return ProcessResponse(
		sttText=stt_text,
		commandText=dispatch_result["command"],
		ttsText=tts_text,
		intent=dispatch_result["intent"],
		errorEventId=(dispatch_result.get("error_event") or {}).get("id"),
		errorTimestamp=(dispatch_result.get("error_event") or {}).get("timestamp"),
	)


def _run_parallel_audio_tasks(audio_path: str) -> tuple[str, dict]:
	with ThreadPoolExecutor(max_workers=2) as pool:
		stt_future = pool.submit(stt.transcribe_audio, audio_path)
		auth_future = pool.submit(identify_speaker_from_file, audio_path)
		stt_text = stt_future.result()
		speaker = auth_future.result()
	return stt_text, speaker


def _cleanup_expired_auth_sessions() -> None:
	now = datetime.now(timezone.utc)
	expired_tokens = [token for token, data in auth_sessions.items() if data["expiresAt"] <= now]
	for token in expired_tokens:
		auth_sessions.pop(token, None)


def _get_auth_session(auth_token: str) -> dict | None:
	_cleanup_expired_auth_sessions()
	return auth_sessions.get(auth_token)


def _create_auth_session(speaker: dict) -> tuple[str, dict]:
	token = str(uuid4())
	auth_sessions[token] = {
		"speakerName": speaker.get("name", "Unknown"),
		"speakerRole": speaker.get("role", "guest"),
		"speakerConfidence": float(speaker.get("confidence", 0.0)),
		"expiresAt": datetime.now(timezone.utc) + timedelta(seconds=VOICE_AUTH_SESSION_SECONDS),
	}
	return token, auth_sessions[token]


@app.get("/health")
def health() -> dict:
	return {"status": "ok"}


@app.get("/api/settings", response_model=AssistantSettingsResponse)
def get_settings() -> AssistantSettingsResponse:
	global runtime_settings
	runtime_settings = settings_service.load()
	return AssistantSettingsResponse(**runtime_settings)


@app.put("/api/settings", response_model=AssistantSettingsResponse)
def update_settings(request: AssistantSettingsRequest) -> AssistantSettingsResponse:
	global runtime_settings
	global stt

	runtime_settings = settings_service.save(request.model_dump())
	stt = settings_service.create_stt(runtime_settings)
	_preload_stt_in_background(stt)
	return AssistantSettingsResponse(**runtime_settings)


@app.get("/api/settings/effective", response_model=EffectiveSettingsResponse)
def get_effective_settings() -> EffectiveSettingsResponse:
	active_settings = runtime_settings.copy()
	return EffectiveSettingsResponse(
		theme=active_settings["theme"],
		speechModel=active_settings["speechModel"],
		computeDevice=active_settings["computeDevice"],
		responseMode=active_settings["responseMode"],
		voiceVolume=active_settings["voiceVolume"],
		activeSttModel=stt.model_size,
		activeSttDevice=stt.device,
	)

@app.post("/api/process", response_model=ProcessResponse)
def process_command(request: ProcessRequest) -> ProcessResponse:
	stt_text = stt.transcribe_text(request.text)
	return _build_process_response(stt_text)


@app.post("/api/chat/turn", response_model=ChatTurnResponse)
def chat_turn(request: ChatTurnRequest) -> ChatTurnResponse:
	result = ai_router.handle_text(request.text)
	return ChatTurnResponse(**result)


@app.post("/api/process-audio", response_model=ProcessResponse)
async def process_audio_command(audio: UploadFile = File(...)) -> ProcessResponse:
	suffix = Path(audio.filename or "command.webm").suffix or ".webm"
	temp_path: str | None = None

	try:
		with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
			shutil.copyfileobj(audio.file, temp_file)
			temp_path = temp_file.name

		stt_text = stt.transcribe_audio(temp_path)
		if not stt_text:
			raise HTTPException(status_code=400, detail="No speech detected in audio")

		return _build_process_response(stt_text)
	except HTTPException:
		raise
	except RuntimeError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Audio processing failed: {exc}") from exc
	finally:
		await audio.close()
		if temp_path:
			Path(temp_path).unlink(missing_ok=True)


@app.post("/api/process-audio-secure", response_model=SecureProcessResponse)
async def process_audio_command_secure(audio: UploadFile = File(...)) -> SecureProcessResponse:
	suffix = Path(audio.filename or "command.webm").suffix or ".webm"
	temp_path: str | None = None

	try:
		with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
			shutil.copyfileobj(audio.file, temp_file)
			temp_path = temp_file.name

		stt_text, speaker = _run_parallel_audio_tasks(temp_path)
		if not stt_text:
			raise HTTPException(status_code=400, detail="No speech detected in audio")

		intent, _ = dispatcher.resolve_intent(stt_text)
		access_granted = can_execute(speaker, intent)

		if not access_granted:
			denial = "Voice recognized but this role is not allowed for the requested command."
			if speaker.get("role") == "guest":
				denial = "Voice not recognized. Access denied."

			return SecureProcessResponse(
				sttText=stt_text,
				commandText="Authorization blocked",
				ttsText=denial,
				intent=intent,
				speakerName=speaker.get("name", "Unknown"),
				speakerRole=speaker.get("role", "guest"),
				speakerConfidence=float(speaker.get("confidence", 0.0)),
				accessGranted=False,
				denialReason=denial,
			)

		response = _build_process_response(stt_text)
		token, session = _create_auth_session(speaker)
		return SecureProcessResponse(
			**response.model_dump(),
			speakerName=speaker.get("name", "Unknown"),
			speakerRole=speaker.get("role", "guest"),
			speakerConfidence=float(speaker.get("confidence", 0.0)),
			accessGranted=True,
			authToken=token,
			expiresInSeconds=VOICE_AUTH_SESSION_SECONDS,
		)
	except HTTPException:
		raise
	except RuntimeError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Secure audio processing failed: {type(exc).__name__}: {exc}") from exc
	finally:
		await audio.close()
		if temp_path:
			Path(temp_path).unlink(missing_ok=True)


@app.post("/api/process-audio-session", response_model=SecureProcessResponse)
async def process_audio_command_with_session(
	audio: UploadFile = File(...),
	authToken: str = Form(...),
) -> SecureProcessResponse:
	session = _get_auth_session(authToken)
	if session is None:
		raise HTTPException(status_code=401, detail="Voice auth session is missing or expired")

	suffix = Path(audio.filename or "command.webm").suffix or ".webm"
	temp_path: str | None = None

	try:
		with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
			shutil.copyfileobj(audio.file, temp_file)
			temp_path = temp_file.name

		stt_text = stt.transcribe_audio(temp_path)
		if not stt_text:
			raise HTTPException(status_code=400, detail="No speech detected in audio")

		intent, _ = dispatcher.resolve_intent(stt_text)
		if not can_execute({"role": session["speakerRole"]}, intent):
			denial = "Role is not allowed for this command."
			return SecureProcessResponse(
				sttText=stt_text,
				commandText="Authorization blocked",
				ttsText=denial,
				intent=intent,
				speakerName=session["speakerName"],
				speakerRole=session["speakerRole"],
				speakerConfidence=session["speakerConfidence"],
				accessGranted=False,
				denialReason=denial,
			)

		response = _build_process_response(stt_text)
		return SecureProcessResponse(
			**response.model_dump(),
			speakerName=session["speakerName"],
			speakerRole=session["speakerRole"],
			speakerConfidence=session["speakerConfidence"],
			accessGranted=True,
			authToken=authToken,
			expiresInSeconds=max(
				0,
				int((session["expiresAt"] - datetime.now(timezone.utc)).total_seconds()),
			),
		)
	except HTTPException:
		raise
	except RuntimeError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Session audio processing failed: {type(exc).__name__}: {exc}") from exc
	finally:
		await audio.close()
		if temp_path:
			Path(temp_path).unlink(missing_ok=True)


@app.post("/api/auth-voice", response_model=VoiceAuthResponse)
async def auth_voice(audio: UploadFile = File(...)) -> VoiceAuthResponse:
	suffix = Path(audio.filename or "auth.webm").suffix or ".webm"
	temp_path: str | None = None

	try:
		with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
			shutil.copyfileobj(audio.file, temp_file)
			temp_path = temp_file.name

		speaker = identify_speaker_from_file(temp_path)
		if speaker.get("role") == "guest":
			return VoiceAuthResponse(
				speakerName=speaker.get("name", "Unknown"),
				speakerRole=speaker.get("role", "guest"),
				speakerConfidence=float(speaker.get("confidence", 0.0)),
				accessGranted=False,
				reason="Voice not recognized.",
			)

		token, session = _create_auth_session(speaker)

		return VoiceAuthResponse(
			speakerName=session["speakerName"],
			speakerRole=session["speakerRole"],
			speakerConfidence=session["speakerConfidence"],
			accessGranted=True,
			authToken=token,
			expiresInSeconds=VOICE_AUTH_SESSION_SECONDS,
		)
	except RuntimeError as exc:
		raise HTTPException(status_code=500, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Voice authentication failed: {exc}") from exc
	finally:
		await audio.close()
		if temp_path:
			Path(temp_path).unlink(missing_ok=True)


@app.post("/api/process-secure-text", response_model=SecureProcessResponse)
def process_secure_text(request: SecureTextProcessRequest) -> SecureProcessResponse:
	session = _get_auth_session(request.authToken)
	if session is None:
		raise HTTPException(status_code=401, detail="Voice auth session is missing or expired")

	stt_text = request.text.strip()
	if not stt_text:
		raise HTTPException(status_code=400, detail="No command text provided")

	intent, _ = dispatcher.resolve_intent(stt_text)
	if not can_execute({"role": session["speakerRole"]}, intent):
		denial = "Role is not allowed for this command."
		return SecureProcessResponse(
			sttText=stt_text,
			commandText="Authorization blocked",
			ttsText=denial,
			intent=intent,
			speakerName=session["speakerName"],
			speakerRole=session["speakerRole"],
			speakerConfidence=session["speakerConfidence"],
			accessGranted=False,
			denialReason=denial,
		)

	response = _build_process_response(stt_text)
	return SecureProcessResponse(
		**response.model_dump(),
		speakerName=session["speakerName"],
		speakerRole=session["speakerRole"],
		speakerConfidence=session["speakerConfidence"],
		accessGranted=True,
	)


@app.get("/api/custom-commands", response_model=list[CustomCommandPayload])
def get_custom_commands() -> list[CustomCommandPayload]:
	commands = load_custom_commands()
	return [CustomCommandPayload(**command) for command in commands]


@app.put("/api/custom-commands", response_model=list[CustomCommandPayload])
def put_custom_commands(commands: list[CustomCommandPayload]) -> list[CustomCommandPayload]:
	cleaned = save_custom_commands([command.model_dump() for command in commands])
	return [CustomCommandPayload(**command) for command in cleaned]


@app.get("/api/errors", response_model=list[ErrorEvent])
def list_errors() -> list[ErrorEvent]:
	events = error_store.list_errors()
	return [ErrorEvent(**event) for event in events]


@app.delete("/api/errors/{event_id}")
def delete_error(event_id: str) -> dict:
	deleted = error_store.delete_error(event_id)
	if not deleted:
		raise HTTPException(status_code=404, detail="Error event not found")
	return {"deleted": True, "id": event_id}


@app.get("/api/errors/export")
def export_errors() -> Response:
	csv_data = error_store.export_csv()
	headers = {"Content-Disposition": "attachment; filename=error_events.csv"}
	return Response(content=csv_data, media_type="text/csv", headers=headers)


@app.get("/api/wakeword/status")
def wakeword_status() -> dict:
	return wakeword_service.status()


@app.post("/api/wakeword/detect", response_model=WakewordDetectResponse)
def wakeword_detect(request: WakewordDetectRequest) -> WakewordDetectResponse:
	result = wakeword_service.detect_from_samples(request.samples, request.sampleRate)
	return WakewordDetectResponse(**result)



@app.get("/api/building/multimedia-lights/{state}")
def multimedia_lights_get(state: str) -> dict:
	try:
		return set_multimedia_room_lights(state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/building/multimedia-lights/{state}")
def multimedia_lights_post(state: str) -> dict:
	try:
		return set_multimedia_room_lights(state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/building/room-lights/{room}/{state}")
def room_lights_get(room: str, state: str) -> dict:
	try:
		return set_room_lights(room, state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/building/room-lights/{room}/{state}")
def room_lights_post(room: str, state: str) -> dict:
	try:
		return set_room_lights(room, state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/building/kitchen-lights/{state}")
def kitchen_lights_get(state: str) -> dict:
	try:
		return set_room_lights("kitchen", state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/building/bathroom-lights/{state}")
def bathroom_lights_get(state: str) -> dict:
	try:
		return set_room_lights("bathroom", state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/building/iot-lights/{state}")
def iot_lights_get(state: str) -> dict:
	try:
		return set_room_lights("iot", state)
	except RuntimeError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc

