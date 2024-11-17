#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

'''Echo cancellation using VSLMS filter (Mathews’s adaptation) with adjustments for stability.'''

import logging
import minimal
import buffer
import padasip as pa  # Importing padasip library for VSLMS filter
import numpy as np

class Echo_Cancellation(buffer.Buffering):
    def __init__(self):
        super().__init__()
        logging.info(__doc__)
        
        # Configure VSLMS filter with Mathews’s adaptation from padasip with reduced parameters for stability
        self.vslms_filter = pa.filters.FilterVSLMS_Mathews(
            n=1,          # Set number of taps to 1 for single-channel compatibility
            mu=1e-4,      # Even lower initial step size
            ro=1e-6       # Further reduced step-size increment rate for stability
        )
        
    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Process and cancel echo in real-time using VSLMS (Mathews’s adaptation) with input normalization.'''
        
        # Send recorded data
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        packed_chunk = self.pack(self.chunk_number, ADC)
        self.send(packed_chunk)

        # Run VSLMS filter on received chunk
        chunk = self.unbuffer_next_chunk()
        
        # Normalize inputs to a smaller range to prevent overflow
        scale_factor = 1e-3
        chunk_2d = (chunk.flatten().reshape(-1, 1)) * scale_factor  # Convert to shape (frames, 1)
        adc_2d = (ADC.flatten().reshape(-1, 1)) * scale_factor      # Convert to shape (frames, 1)

        # Apply VSLMS to cancel echo
        echo_cancelled_chunk_2d, error, _ = self.vslms_filter.run(chunk_2d, adc_2d)

        # Scale the output back up and clip to prevent overflow
        echo_cancelled_chunk_2d = np.clip(echo_cancelled_chunk_2d / scale_factor, -32768, 32767)

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
