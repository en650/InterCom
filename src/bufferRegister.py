#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

"""Over minimal, implements a random access buffer structure for hiding the jitter."""

import argparse
import sounddevice as sd
import numpy as np
import socket
import time
import psutil
import math
import struct
import threading
import minimal
import soundfile as sf
import logging
import csv

minimal.parser.add_argument("-b", "--buffering_time", type=int, default=150, help="Milliseconds to buffer")

class Buffering(minimal.Minimal):

    CHUNK_NUMBERS = 1 << 15  # Enough for most buffering times.

    def __init__(self):
        ''' Initializes the buffer and sets up CSV logging. '''
        super().__init__()
        logging.info(__doc__)
        if minimal.args.buffering_time <= 0:
            minimal.args.buffering_time = 1  # ms
        logging.info(f"buffering_time = {minimal.args.buffering_time} milliseconds")
        
        self.chunks_to_buffer = int(math.ceil(minimal.args.buffering_time / 1000 / self.chunk_time))
        self.zero_chunk = self.generate_zero_chunk()
        self.cells_in_buffer = self.chunks_to_buffer * 2
        self._buffer = [None] * self.cells_in_buffer
        for i in range(self.cells_in_buffer):
            self._buffer[i] = self.zero_chunk
        self.chunk_number = 0
        self.played_chunk_number = 0
        
        # Setup CSV logging
        self.csv_filename = "buffer_status_log.csv"
        with open(self.csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Chunks in Buffer"])  # CSV header
        logging.info(f"Logging buffer status to {self.csv_filename}")
        
        logging.info(f"chunks_to_buffer = {self.chunks_to_buffer}")

    def log_buffer_status(self):
        ''' Log the current number of chunks in the buffer to a CSV file. '''
        chunks_in_buffer = (self.chunk_number - self.played_chunk_number) % self.cells_in_buffer
        current_time = time.time()  # Log the timestamp
        
        # Write to CSV
        with open(self.csv_filename, mode='a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([current_time, chunks_in_buffer])
        
        logging.debug(f"Logged buffer status: {chunks_in_buffer} chunks at {current_time}")

    def pack(self, chunk_number, chunk):
        '''Concatenates a chunk number to the chunk.'''
        packed_chunk = struct.pack("!H", chunk_number) + chunk.tobytes()
        return packed_chunk

    def unpack(self, packed_chunk):
        '''Splits the packed chunk into a chunk number and a chunk.'''
        (chunk_number,) = struct.unpack("!H", packed_chunk[:2])
        chunk = packed_chunk[2:]
        chunk = np.frombuffer(chunk, dtype=np.int16)
        return chunk_number, chunk

    def buffer_chunk(self, chunk_number, chunk):
        self._buffer[chunk_number % self.cells_in_buffer] = chunk

    def unbuffer_next_chunk(self):
        chunk = self._buffer[self.played_chunk_number % self.cells_in_buffer]
        return chunk

    def play_chunk(self, DAC, chunk):
        self.played_chunk_number = (self.played_chunk_number + 1) % self.cells_in_buffer
        chunk = chunk.reshape(minimal.args.frames_per_chunk, self.NUMBER_OF_CHANNELS)
        DAC[:] = chunk

    def receive_and_buffer(self):
        if __debug__:
            print(next(minimal.spinner), end='\b', flush=True)
        packed_chunk = self.receive()
        chunk_number, chunk = self.unpack(packed_chunk)
        self.buffer_chunk(chunk_number, chunk)
        return chunk_number

    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        packed_chunk = self.pack(self.chunk_number, ADC)  # Properly packed using `Buffering.pack`
        self.send(packed_chunk)
        chunk = self.unbuffer_next_chunk()
        self.play_chunk(DAC, chunk)

    def _read_IO_and_play(self, DAC, frames, time, status):
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        read_chunk = self.read_chunk_from_file()
        packed_chunk = self.pack(self.chunk_number, read_chunk)
        self.send(packed_chunk)
        chunk = self.unbuffer_next_chunk()
        self.play_chunk(DAC, chunk)
        return read_chunk

    def log_buffer_status_every_second(self):
        ''' Continuously log the buffer status every second in a separate thread. '''
        while True:
            self.log_buffer_status()  # Log buffer status
            time.sleep(1)  # Wait for 1 second

    def run(self):
        '''Creates the stream, installs the callback function, and starts logging buffer status every second.'''
        logging.info("Press CTRL+c to quit")
        self.played_chunk_number = 0

        # Start the logging thread for recording buffer status every second
        logging_thread = threading.Thread(target=self.log_buffer_status_every_second)
        logging_thread.daemon = True
        logging_thread.start()

        with self.stream(self._handler):
            first_received_chunk_number = self.receive_and_buffer()
            logging.debug(f"first_received_chunk_number = {first_received_chunk_number}")

            self.played_chunk_number = (first_received_chunk_number - self.chunks_to_buffer) % self.cells_in_buffer

            while True:  # and not self.input_exhausted:
                self.receive_and_buffer()

class Buffering__verbose(Buffering, minimal.Minimal__verbose):

    def __init__(self):
        super().__init__()

    def send(self, packed_chunk):
        '''Computes the number of sent bytes and the number of sent packets.'''
        Buffering.send(self, packed_chunk)
        self.sent_bytes_count += len(packed_chunk)
        self.sent_messages_count += 1

    def receive(self):
        '''Computes the number of received bytes and the number of received packets.'''
        packed_chunk = Buffering.receive(self)
        self.received_bytes_count += len(packed_chunk)
        self.received_messages_count += 1
        return packed_chunk

    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        if minimal.args.show_samples:
            self.show_recorded_chunk(ADC)

        super()._record_IO_and_play(ADC, DAC, frames, time, status)

        if minimal.args.show_samples:
            self.show_played_chunk(DAC)

        self.recorded_chunk = DAC

    def _read_IO_and_play(self, DAC, frames, time, status):
        read_chunk = super()._read_IO_and_play(DAC, frames, time, status)

        if minimal.args.show_samples:
            self.show_recorded_chunk(read_chunk)
            self.show_played_chunk(DAC)

        self.recorded_chunk = DAC

        return read_chunk

    def loop_receive_and_buffer(self):
        first_received_chunk_number = self.receive_and_buffer()
        if __debug__:
            print("first_received_chunk_number =", first_received_chunk_number)
        self.played_chunk_number = (first_received_chunk_number - self.chunks_to_buffer) % self.cells_in_buffer
        while self.total_number_of_sent_chunks < self.chunks_to_sent:  # and not self.input_exhausted:
            self.receive_and_buffer()
            self.update_display()  # PyGame cannot run in a thread :-/

    def run(self):
        cycle_feedback_thread = threading.Thread(target=self.loop_cycle_feedback)
        cycle_feedback_thread.daemon = True        
        self.print_running_info()
        super().print_header()
        self.played_chunk_number = 0
        with self.stream(self._handler):
            cycle_feedback_thread.start()
            self.loop_receive_and_buffer()

try:
    import argcomplete  # <tab> completion for argparse.
except ImportError:
    logging.warning("Unable to import argcomplete (optional)")

if __name__ == "__main__":
    minimal.parser.description = __doc__

    try:
        argcomplete.autocomplete(minimal.parser)
    except Exception:
        logging.warning("argcomplete not working :-/")

    minimal.args = minimal.parser.parse_known_args()[0]
    
    if minimal.args.list_devices:
        print("Available devices:")
        print(sd.query_devices())
        quit()

    if minimal.args.show_stats or minimal.args.show_samples:
        intercom = Buffering__verbose()
    else:
        intercom = Buffering()

    try:
        intercom.run()
    except KeyboardInterrupt:
        minimal.parser.exit("\nSIGINT received")
    finally:
        intercom.print_final_averages()
