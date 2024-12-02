#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
'''Echo cancellation using Online Centered Normalized Least-Mean-Square (OCNLMS) filter from padasip.'''

import logging
import minimal
import buffer
import padasip as pa  # Import padasip library.
import numpy as np
import signal
import sys
import threading  # Multi-threading
import time
import psutil  # For CPU and memory usage monitoring

# Handle SIGINT (Ctrl+C) for clean exit
def signal_handler(sig, frame):
    print("\nInterruption received. Exiting the program...")
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

class Echo_Cancellation(buffer.Buffering):
    def __init__(self, n=4, mu=0.5, eps=1.0, mem=500, update_interval=50, monitor_interval=1.0):
        '''Initialize the OCNLMS echo cancellation filter.'''
        super().__init__()
        logging.info(__doc__)
        
        # Initialize the OCNLMS filter with given parameters
        self.ocnlms_filter = pa.filters.FilterOCNLMS(n=n, mu=mu, eps=eps, mem=mem)
        self.running = threading.Event()  # Use Event for thread control
        self.running.set()  # Set the event to signal that the thread should run
        self.chunk_counter = 0  # Counter for processed chunks
        self.update_interval = update_interval  # Number of chunks between weight updates 
        self.monitor_interval = monitor_interval  # Interval for resource monitoring
        self.monitor_thread = threading.Thread(target=self._monitor_resources, daemon=True)
        self.monitor_thread.start()

    def _monitor_resources(self):
        '''Monitor and log CPU and memory usage.'''
        while self.running.is_set():
            try:
                # Per-core CPU usage
                cpu_per_core = psutil.cpu_percent(percpu=True)
                cpu_report = ", ".join(f"Core {i}: {usage}%" for i, usage in enumerate(cpu_per_core))
                logging.info(f"CPU usage per core: {cpu_report}")
                
                # Memory usage (system-wide)
                memory_info = psutil.virtual_memory()
                logging.info(
                    f"Memory Usage: {memory_info.percent}% used, "
                    f"Available: {memory_info.available / (1024 ** 2):.2f} MB, "
                    f"Total: {memory_info.total / (1024 ** 2):.2f} MB"
                )
                
                # Memory usage (current process)
                process = psutil.Process()
                process_memory = process.memory_info()
                logging.info(
                    f"Process Memory: RSS={process_memory.rss / (1024 ** 2):.2f} MB, "
                    f"VMS={process_memory.vms / (1024 ** 2):.2f} MB"
                )
            except Exception as e:
                logging.error(f"Error monitoring resources: {e}")
            time.sleep(self.monitor_interval)

    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Echo cancellation during audio processing in real-time, sending audio to the peer.'''
        if not self.running.is_set():
            raise sd.CallbackStop  # Stop the stream if the event is cleared

        try:
            # Use the OCNLMS filter
            x = ADC.flatten()[:self.ocnlms_filter.n].astype(np.float32)
            y_pred = self.ocnlms_filter.predict(x)
            target = ADC.flatten()[0]
            error = target - y_pred

            # Update weights every `update_interval` chunks
            self.chunk_counter += 1
            if self.chunk_counter >= self.update_interval:
                self.ocnlms_filter.adapt(error, x)
                print("updated")  # Print statement for updates
                self.chunk_counter = 0  # Reset the counter

            # Send the chunk to the peer
            self.send(self.pack(self.chunk_number, ADC))
            self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS

            # Receive and play the processed audio
            received_chunk = self.receive()
            if received_chunk:
                chunk_number, received_audio = self.unpack(received_chunk)
                DAC[:] = received_audio.reshape(DAC.shape)
            else:
                DAC[:] = self.zero_chunk
        except Exception as e:
            logging.error(f"Error in _record_IO_and_play: {e}")
            DAC[:] = self.zero_chunk

    def run(self):
        '''Runs the audio processing loop in a separate thread.'''
        logging.info("Starting Echo Cancellation...")
        self.stream = self.mic_stream(self._record_IO_and_play)

        # Launch the audio processing loop in a thread
        self.audio_thread = threading.Thread(target=self._audio_loop)
        self.audio_thread.start()

    def _audio_loop(self):
        '''Main audio processing loop.'''
        with self.stream:
            while self.running.is_set():
                time.sleep(0.01)  # Avoid busy-waiting with a small sleep interval

    def close(self):
        '''Cleanly shut down the audio stream and resources.'''
        logging.info("Shutting down Echo Cancellation...")
        self.running.clear()  # Clear the event to signal the thread to stop
        if self.audio_thread.is_alive():
            self.audio_thread.join()  # Wait for the audio thread to finish
        self.sock.close()  # Close the network socket

class Echo_Cancellation__verbose(Echo_Cancellation, buffer.Buffering__verbose):
    def __init__(self):
        super().__init__()

try:
    import argcomplete  # Tab completion for argparse
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
        print("\nSIGINT received: closing the program...")
        intercom.close()  # Close resources explicitly
        sys.exit(0)  # Exit forcefully
    finally:
        intercom.print_final_averages()
