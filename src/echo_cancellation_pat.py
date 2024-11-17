#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

'''Echo cancellation using Online Centered Normalized Least-Mean-Square (OCNLMS) filter from padasip.'''

import logging
import numpy as np
import minimal
import buffer
import padasip as pa
import signal
import sys
import threading

# Manejo de la señal SIGINT para salida limpia
def signal_handler(sig, frame):
    print("\nInterrupción recibida. Saliendo del programa...")
    sys.exit(0)

# Conectar la señal SIGINT (CTRL+C) al manejador
signal.signal(signal.SIGINT, signal_handler)

class Echo_Cancellation(buffer.Buffering):
    def __init__(self, n=4, mu=0.5, eps=1.0, mem=100):
        '''Initialize the OCNLMS echo cancellation filter.'''
        super().__init__()
        logging.info(__doc__)

        # Initialize the OCNLMS filter from padasip with given parameters
        self.ocnlms_filter = pa.filters.FilterOCNLMS(n=n, mu=mu, eps=eps, mem=mem)
        self.running = True  # Control para el bucle de audio

    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Echo cancellation during audio processing in real-time, sending audio to the peer.'''
        if not self.running:
            raise sd.CallbackStop  # Detiene el stream si `running` es False

        x = ADC.flatten()[:self.ocnlms_filter.n].astype(np.float32)
        y_pred = self.ocnlms_filter.predict(x)
        target = ADC.flatten()[0]
        error = target - y_pred
        self.ocnlms_filter.adapt(error, x)
        self.send(self.pack(self.chunk_number, ADC))
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS

        try:
            received_chunk = self.receive()
            chunk_number, received_audio = self.unpack(received_chunk)
            DAC[:] = received_audio.reshape(DAC.shape)
        except Exception:
            DAC[:] = self.zero_chunk

    def _read_IO_and_play(self, DAC, frames, time, status):
        if not self.running:
            raise sd.CallbackStop  # Detiene el stream si `running` es False

        read_chunk = self.read_chunk_from_file().flatten()[:self.ocnlms_filter.n].astype(np.float32)
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
        audio_thread.join()  # Espera a que el hilo termine

    def _audio_loop(self):
        '''Bucle principal del audio.'''
        with self.stream:
            while self.running:
                pass

    def close(self):
        '''Detiene el streaming de audio y cierra los recursos.'''
        print("Cerrando recursos de audio...")
        self.running = False  # Detiene el bucle de audio
        self.stream.stop()  # Detiene el stream explícitamente
        self.sock.close()  # Cierra el socket de red

class Echo_Cancellation__verbose(Echo_Cancellation, buffer.Buffering__verbose):
    #def __init__(self):
    #    super().__init__()
    pass
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
        intercom.close()  # Cerrar recursos explícitamente
        sys.exit(0)  # Salir forzadamente
    finally:
        intercom.print_final_averages()
