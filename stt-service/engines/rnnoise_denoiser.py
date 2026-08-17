"""
RNNoise Streaming and Batch Denoiser for STT Service.

Loads librnnoise directly via ctypes with zero fragile python packaging dependencies.
Supports real-time streaming audio (16kHz mono PCM) with state continuity and batch denoising.
"""

import ctypes
import os
import platform
import sys
from typing import AsyncIterator, Iterator, Optional, Tuple
import numpy as np
from scipy import signal

# Find and load the native librnnoise library
def _load_rnnoise_lib():
    system = platform.system()
    possible_paths = [
        # Local engines/lib directory
        os.path.join(os.path.dirname(__file__), "lib", "librnnoise.dylib"),
        os.path.join(os.path.dirname(__file__), "lib", "librnnoise.so"),
        os.path.join(os.path.dirname(__file__), "lib", "rnnoise.dll"),
        # Site-packages pyrnnoise directory
        os.path.join(sys.prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages", "pyrnnoise", "librnnoise.dylib"),
        os.path.join(sys.prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages", "pyrnnoise", "librnnoise.so"),
        # Standard system locations
        "/usr/local/lib/librnnoise.dylib",
        "/usr/local/lib/librnnoise.so",
        "/usr/lib/librnnoise.so",
    ]

    for p in possible_paths:
        if os.path.exists(p):
            try:
                lib = ctypes.CDLL(p)
                lib.rnnoise_create.argtypes = [ctypes.c_void_p]
                lib.rnnoise_create.restype = ctypes.c_void_p
                lib.rnnoise_destroy.argtypes = [ctypes.c_void_p]
                lib.rnnoise_get_frame_size.restype = ctypes.c_int
                lib.rnnoise_process_frame.argtypes = [
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_float),
                    ctypes.POINTER(ctypes.c_float),
                ]
                lib.rnnoise_process_frame.restype = ctypes.c_float
                return lib
            except Exception:
                continue

    return None

_RNNOISE_LIB = _load_rnnoise_lib()


class RNNoiseStreamDenoiser:
    """
    Stateful streaming audio denoiser using RNNoise.
    Processes 16kHz 16-bit mono PCM chunks in real time.
    """

    FRAME_SIZE_48K = 480  # 10ms @ 48kHz
    FRAME_SIZE_16K = 160  # 10ms @ 16kHz
    BYTES_PER_FRAME_16K = 320  # 160 samples * 2 bytes

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._lib = _RNNOISE_LIB
        self._state = None
        self._buffer = bytearray()
        
        if self._lib is not None:
            self._state = self._lib.rnnoise_create(None)

    def __del__(self):
        self.destroy()

    def destroy(self):
        """Release native C RNNoise state."""
        if self._state is not None and self._lib is not None:
            try:
                self._lib.rnnoise_destroy(self._state)
            except Exception:
                pass
            self._state = None

    def reset(self):
        """Reset internal buffer and RNNoise state."""
        self.destroy()
        self._buffer.clear()
        if self._lib is not None:
            self._state = self._lib.rnnoise_create(None)

    def _process_single_frame_16k(self, pcm_frame_bytes: bytes) -> bytes:
        """
        Process a single 160-sample (320 byte) 16kHz PCM frame through RNNoise.
        """
        if self._state is None or self._lib is None:
            return pcm_frame_bytes

        # Convert 16kHz int16 samples to float32
        samples_16k = np.frombuffer(pcm_frame_bytes, dtype=np.int16).astype(np.float32)
        if len(samples_16k) != self.FRAME_SIZE_16K:
            samples_16k = np.pad(samples_16k, (0, max(0, self.FRAME_SIZE_16K - len(samples_16k))))[:self.FRAME_SIZE_16K]

        # Upsample 3x: 16kHz (160 samples) -> 48kHz (480 samples)
        samples_48k = signal.resample_poly(samples_16k, up=3, down=1).astype(np.float32)

        # Call RNNoise C library (operates in-place on 480 float samples)
        ptr = samples_48k.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
        self._lib.rnnoise_process_frame(self._state, ptr, ptr)

        # Downsample 3x: 48kHz (480 samples) -> 16kHz (160 samples)
        denoised_16k = signal.resample_poly(samples_48k, up=1, down=3)

        # Clip and convert back to 16-bit PCM bytes
        denoised_int16 = np.clip(denoised_16k, -32768.0, 32767.0).astype(np.int16)
        return denoised_int16.tobytes()

    def process_chunk(self, audio_chunk_bytes: bytes) -> bytes:
        """
        Feed an arbitrary-sized chunk of 16kHz 16-bit PCM bytes and return
        the denoised bytes. Any leftover partial frame is retained in buffer.
        """
        if not audio_chunk_bytes:
            return b""

        if self._state is None or self._lib is None:
            return audio_chunk_bytes

        self._buffer.extend(audio_chunk_bytes)
        output = bytearray()

        while len(self._buffer) >= self.BYTES_PER_FRAME_16K:
            frame_bytes = bytes(self._buffer[:self.BYTES_PER_FRAME_16K])
            del self._buffer[:self.BYTES_PER_FRAME_16K]
            output.extend(self._process_single_frame_16k(frame_bytes))

        return bytes(output)

    def flush(self) -> bytes:
        """
        Flush any remaining audio in the buffer at the end of the stream.
        """
        if not self._buffer:
            return b""

        if self._state is None or self._lib is None:
            remaining = bytes(self._buffer)
            self._buffer.clear()
            return remaining

        orig_len = len(self._buffer)
        orig_samples = orig_len // 2

        # Pad to full frame
        self._buffer.extend(b"\x00" * (self.BYTES_PER_FRAME_16K - orig_len))
        frame_bytes = bytes(self._buffer[:self.BYTES_PER_FRAME_16K])
        self._buffer.clear()

        denoised_frame = self._process_single_frame_16k(frame_bytes)
        # Truncate back to original sample count (2 bytes per sample)
        return denoised_frame[:orig_samples * 2]

    @classmethod
    def denoise_bytes(cls, audio_bytes: bytes, sample_rate: int = 16000) -> bytes:
        """
        Convenience batch denoiser for unary/batch audio data.
        """
        if not audio_bytes or _RNNOISE_LIB is None:
            return audio_bytes

        denoiser = cls(sample_rate=sample_rate)
        try:
            out = bytearray()
            out.extend(denoiser.process_chunk(audio_bytes))
            out.extend(denoiser.flush())
            return bytes(out)
        finally:
            denoiser.destroy()
