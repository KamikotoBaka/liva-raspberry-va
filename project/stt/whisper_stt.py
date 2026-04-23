import os
from pathlib import Path


class FasterWhisperSTT:
	def __init__(self, model_size: str = "base", device: str = "cpu") -> None:
		self.model_size = model_size
		self.device = device
		self.compute_type = "float16" if device == "cuda" else "int8"
		self.download_root = Path(__file__).resolve().parent.parent / "models" / "faster-whisper"
		self._model = None

		# Windows often cannot create symlinks in the default HF cache.
		# Suppress the warning and use a project-local model cache instead.
		os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

	def _load_model(self):
		if self._model is not None:
			return self._model

		try:
			from faster_whisper import WhisperModel
		except ImportError:
			return None

		self.download_root.mkdir(parents=True, exist_ok=True)
		self._model = WhisperModel(
			self.model_size,
			device=self.device,
			compute_type=self.compute_type,
			download_root=str(self.download_root),
		)
		return self._model

	def preload(self) -> None:
		model = self._load_model()
		if model is None:
			raise RuntimeError("faster-whisper is not installed")

	def transcribe_audio(self, audio_path: str) -> str:
		model = self._load_model()
		if model is None:
			raise RuntimeError("faster-whisper is not installed")

		segments, _ = model.transcribe(audio_path)
		return " ".join(segment.text.strip() for segment in segments).strip()

	def transcribe_text(self, text: str) -> str:
		return text.strip()
