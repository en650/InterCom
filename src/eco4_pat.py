#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

'''Echo cancellation using Online Centered Normalized Least-Mean-Square (OCNLMS) filter from padasip with optimized resource usage.'''

import logging
import numpy as np
import minimal
import buffer
import padasip as pa
import signal
import sys
import threading
import time

def signal_handler(sig, frame):
    print("\nInterrupción recibida. Saliendo del programa...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

class Echo_Cancellation(buffer.Buffering):
    def __init__(self, n=1, mu=0.1, eps=1.0, mem=50):
        '''Initialize the OCNLMS echo cancellation filter with optimized parameters.'''
        super().__init__()
        logging.info(__doc__)

        # Initialize the OCNLMS filter from padasip with optimized parameters
        self.ocnlms_filter = pa.filters.FilterOCNLMS(n=n, mu=mu, eps=eps, mem=mem)
        self.running = True
        self.chunk_counter = 0  # Counter for conditional chunk processing

        # Ensure `self.ocnlms_filter.w` has the correct shape (n, 1)
        self.ocnlms_filter.w = self.ocnlms_filter.w.reshape(-1, 1)

    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Echo cancellation during audio processing in real-time, sending audio to the peer with optimized processing.'''
        if not self.running:
            raise sd.CallbackStop

        # Process every second chunk only to reduce load
        self.chunk_counter = (self.chunk_counter + 1) % 2
        if self.chunk_counter != 0:
            DAC[:] = ADC  # Bypass processing for this chunk
            return

        # Access only required frames directly and reshape to (n, 1) for compatibility
        x = ADC[:self.ocnlms_filter.n].astype(np.float32).reshape(-1, 1)
        y_pred = self.ocnlms_filter.predict(x)
        target = ADC[0]
        error = target - y_pred
        self.ocnlms_filter.adapt(error, x)  # No shape mismatch with x as 2D

        self.send(self.pack(self.chunk_number, ADC))
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS

        try:
            received_chunk = self.receive()
            chunk_number, received_audio = self.unpack(received_chunk)
            DAC[:] = received_audio.reshape(DAC.shape)
        except Exception:
            DAC[:] = self.zero_chunk

    def _read_IO_and_play(self, DAC, frames, time, status):
        '''Reads audio, applies echo cancellation with optimized processing, and sends audio to DAC.'''
        if not self.running:
            raise sd.CallbackStop

        # Access only required frames directly and reshape to (n, 1) for compatibility
        read_chunk = self.read_chunk_from_file()[:self.ocnlms_filter.n].astype(np.float32).reshape(-1, 1)
        y_pred = self.ocnlms_filter.predict(read_chunk)
        target = read_chunk[0]
        error = target - y_pred
        self.ocnlms_filter.adapt(error, read_chunk)

        self.send(self.pack(self.chunk_number, read_chunk))
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS

        try:
            received_chunk = self.receive()
            chunk_number, received_audio = self.unpack(received_chunk)
            DAC[:] = received_audio.reshape(DAC.shape)
        except Exception:
            DAC[:] = self.zero_chunk
        return read_chunk

    def run(self):
        '''Runs the audio streaming in a separate thread.'''
        self.stream = self.mic_stream(self._record_IO_and_play)
        audio_thread = threading.Thread(target=self._audio_loop)
        audio_thread.start()
        audio_thread.join()

    def _audio_loop(self):
        '''Bucle principal del audio with slight delay to reduce CPU load.'''
        with self.stream:
            while self.running:
                time.sleep(0.01)  # Add a brief sleep to reduce CPU usage

    def close(self):
        '''Stops audio streaming and releases resources.'''
        print("Cerrando recursos de audio...")
        self.running = False
        self.stream.stop()
        self.sock.close()

class Echo_Cancellation__verbose(Echo_Cancellation, buffer.Buffering__verbose):
    def __init__(self):
        super().__init__()

try:
    import argcomplete
except ImportError:
    logging.warning("Unable to import argcomplete (optional)")

if __name__ == "__main__":
    minimal.parser.description = __doc__
    try:
        argcomplete.autocomplete(minimal.parser)
    except Exception:
        logging.warning("argcomplete not working :-/")
    minimal.args = minimal.parser.parse_known_args()[0]

    if minimal.args.show_stats or minimal.args.show_samples or minimal.args.show_spectrum:
        intercom = Echo_Cancellation__verbose()
    else:
        intercom = Echo_Cancellation()
    try:
        intercom.run()
    except KeyboardInterrupt:
        print("\nSIGINT recibido: cerrando el programa...")
        intercom.close()
        sys.exit(0)
    finally:
        intercom.print_final_averages()
