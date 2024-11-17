#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

'''Echo cancellation using SSLMS filter.'''

import logging
import minimal
import buffer
import padasip as pa  # Importing padasip library for SSLMS filter

class Echo_Cancellation(buffer.Buffering):
    def __init__(self):
        super().__init__()
        logging.info(__doc__)
        
        # Configure SSLMS filter from padasip
        self.sslms_filter = pa.filters.FilterSSLMS(
            n=1,  # Set number of taps to 1 for single-channel compatibility
            mu=0.01  # Step size (learning rate); adjust as needed for echo cancellation
        )
        
    def _record_IO_and_play(self, ADC, DAC, frames, time, status):
        '''Process and cancel echo in real-time using SSLMS.'''
        
        # Send recorded data
        self.chunk_number = (self.chunk_number + 1) % self.CHUNK_NUMBERS
        packed_chunk = self.pack(self.chunk_number, ADC)
        self.send(packed_chunk)

        # Run SSLMS filter on received chunk
        chunk = self.unbuffer_next_chunk()
        
        # Flatten and reshape the chunk and ADC to 2D for SSLMS compatibility
        chunk_2d = chunk.flatten().reshape(-1, 1)  # Convert to shape (frames, 1)
        adc_2d = ADC.flatten().reshape(-1, 1)      # Convert to shape (frames, 1)

        # Apply SSLMS to cancel echo
        echo_cancelled_chunk_2d, error, _ = self.sslms_filter.run(chunk_2d, adc_2d)

        # Reshape the processed chunk back to 2D for playback
        echo_cancelled_chunk = echo_cancelled_chunk_2d.reshape((frames, self.NUMBER_OF_CHANNELS))
        
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
