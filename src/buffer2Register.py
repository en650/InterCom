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
        '''Initializes the buffer and sets up CSV logging.'''
        super().__init__()
        logging.info(__doc__)
        if minimal.args.buffering_time <= 0:
            minimal.args.buffering_time = 1  # ms
        logging.info(f"buffering_time = {minimal.args.buffering_time} milliseconds")
        
        # Calculate the number of chunks needed to store in the buffer.
        self.chunks_to_buffer = int(math.ceil(minimal.args.buffering_time / 1000 / self.chunk_time)) 
        self.zero_chunk = self.generate_zero_chunk()
        self.cells_in_buffer = self.chunks_to_buffer * 2
        self._buffer = [None] * self.cells_in_buffer
        for i in range(self.cells_in_buffer):
            self._buffer[i] = self.zero_chunk
        self.chunk_number = 0
        self.played_chunk_number = 0
        self.playback_speed = 1.0  # Start at normal speed
        logging.info(f"chunks_to_buffer = {self.chunks_to_buffer}")
        
        # Setup CSV logging
        self.csv_filename = "buffer2_status_log.csv"
        with open(self.csv_filename, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Chunks in Buffer"])  # CSV header
        logging.info(f"Logging buffer status to {self.csv_filename}")

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
        '''Buffer a chunk using the circular buffer logic.'''
        logging.debug(f"Buffering chunk number: {chunk_number}")
        self._buffer[chunk_number % self.cells_in_buffer] = chunk

    def unbuffer_next_chunk(self):
        '''Retrieve the next chunk from the buffer.'''
        chunk = self._buffer[self.played_chunk_number % self.cells_in_buffer]
        logging.debug(f"Unbuffering chunk number: {self.played_chunk_number}")
        return chunk

    def receive_and_buffer(self):
        '''Receive a packed chunk, unpack it, and store it in the buffer.'''
        packed_chunk, sender = self.sock.recvfrom(self.MAX_PAYLOAD_BYTES)
        chunk_number, chunk = self.unpack(packed_chunk)
        self.buffer_chunk(chunk_number, chunk)
        return chunk_number

    def adjust_playback_speed(self):
        '''Adjust playback speed based on the buffer level.'''
        chunks_in_buffer = (self.chunk_number - self.played_chunk_number) % self.cells_in_buffer
        
        if chunks_in_buffer >=  self.chunks_to_buffer - 2:
            self.playback_speed = 1.05  # Speed up playback to 105% when buffer is healthy
        elif chunks_in_buffer == 3:
            self.playback_speed = 0.95  # Slow down to 95% when 3 chunks are buffered
        elif chunks_in_buffer == 2:
            self.playback_speed = 0.80  # Slow down to 80% when 2 chunks are buffered
        elif chunks_in_buffer == 1:
            self.playback_speed = 0.60  # Slow down to 60% when only 1 chunk is buffered
        else:
            self.playback_speed = 1.0  # Default to normal speed

    def play_chunk(self, DAC, chunk):
        '''Play the audio chunk while adjusting playback speed.'''
        self.played_chunk_number = (self.played_chunk_number + 1) % self.cells_in_buffer
        
        # Reshape the chunk to fit the DAC output
        chunk = chunk.reshape(minimal.args.frames_per_chunk, self.NUMBER_OF_CHANNELS)
        
        # Adjust playback speed dynamically by modifying the number of frames sent to the DAC
        adjusted_frames = int(minimal.args.frames_per_chunk * self.playback_speed)
        DAC[:adjusted_frames] = chunk[:adjusted_frames]
        
        # Fill remaining DAC buffer with zeros if playback is slower
        if adjusted_frames < minimal.args.frames_per_chunk:
            DAC[adjusted_frames:] = 0

    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Record from ADC, send the chunk, and play the next chunk from the buffer.'''
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        packed_chunk = self.pack(self.chunk_number, ADC)
        self.send(packed_chunk)
        
        # Adjust playback speed based on the buffer levels
        self.adjust_playback_speed()
        
        # Play the next chunk from the buffer
        chunk = self.unbuffer_next_chunk()
        self.play_chunk(DAC, chunk)

    def _read_IO_and_play(self, DAC, frames, time, status):
        '''Read from file, send the chunk, and play the next chunk from the buffer.'''
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        read_chunk = self.read_chunk_from_file()
        packed_chunk = self.pack(self.chunk_number, read_chunk)
        self.send(packed_chunk)
        
        # Adjust playback speed based on buffer levels
        self.adjust_playback_speed()
        
        # Play the next chunk from the buffer
        chunk = self.unbuffer_next_chunk()
        self.play_chunk(DAC, chunk)
        return read_chunk

    def log_buffer_status_every_second(self):
        ''' Continuously log the buffer status every second in a separate thread. '''
        while True:
            self.log_buffer_status()  # Log buffer status
            time.sleep(1)  # Wait for 1 second

    def run(self):
        '''Run the audio stream, adjusting for playback speed and buffering logic.'''
        logging.info("Press CTRL+C to quit")
        self.played_chunk_number = 0
        
        # Start the logging thread for recording buffer status every second
        logging_thread = threading.Thread(target=self.log_buffer_status_every_second)
        logging_thread.daemon = True
        logging_thread.start()

        with self.stream(self._handler):
            first_received_chunk_number = self.receive_and_buffer()
            logging.debug(f"First received chunk number = {first_received_chunk_number}")

            self.played_chunk_number = (first_received_chunk_number - self.chunks_to_buffer) % self.cells_in_buffer
            # Select the first chunk to play, buffered <chunks_to_buffer> positions behind.

            while True:
                self.receive_and_buffer()

# Buffering__verbose subclass remains the same

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
