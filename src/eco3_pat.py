#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

'''Echo cancellation using GNGD filter.'''

import logging
import minimal
import buffer
import padasip as pa  # Importing padasip library for GNGD filter
import numpy as np

class Echo_Cancellation(buffer.Buffering):
    def __init__(self):
        super().__init__()
        logging.info(__doc__)
        
        # Configure GNGD filter from padasip
        self.gngd_filter = pa.filters.FilterGNGD(
            n=1,          # Set number of taps to 1 for single-channel compatibility
            mu=0.01       # Initial step size (learning rate)
        )
        
    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Process and cancel echo in real-time using GNGD.'''
        
        # Send recorded data
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        packed_chunk = self.pack(self.chunk_number, ADC)
        self.send(packed_chunk)

        # Run GNGD filter on received chunk
        chunk = self.unbuffer_next_chunk()
        
        # Flatten and reshape the chunk and ADC to 2D for GNGD compatibility
        chunk_2d = chunk.flatten().reshape(-1, 1)  # Convert to shape (frames, 1)
        adc_2d = ADC.flatten().reshape(-1, 1)      # Convert to shape (frames, 1)

        # Apply GNGD to cancel echo
        echo_cancelled_chunk_2d, error, _ = self.gngd_filter.run(chunk_2d, adc_2d)

        # Clip values to prevent overflow and cast to int16 for playback
        echo_cancelled_chunk_2d = np.clip(echo_cancelled_chunk_2d, -32768, 32767)
        
        # Reshape the processed chunk back to 2D for playback
        echo_cancelled_chunk = echo_cancelled_chunk_2d.reshape((frames, self.NUMBER_OF_CHANNELS)).astype(np.int16)
        
        # Play the echo-cancelled chunk
        self.play_chunk(DAC, echo_cancelled_chunk)


class Echo_Cancellation__verbose(Echo_Cancellation, buffer.Buffering__verbose):
    def __init__(self):
        super().__init__()

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

    if minimal.args.show_stats or minimal.args.show_samples or minimal.args.show_spectrum:
        intercom = Echo_Cancellation__verbose()
    else:
        intercom = Echo_Cancellation()
    
    try:
        intercom.run()
    except KeyboardInterrupt:
        minimal.parser.exit("\nSIGINT received")
    finally:
       intercom.print_final_averages()
