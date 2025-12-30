"""
Simple JACK client manager for GUI integration.
Wraps the jack library for canvas use.
"""

import logging
from typing import List, Dict, Optional, Set
import jack

logger = logging.getLogger(__name__)


class JackClientManager:
    """Wrapper around jack.Client for GUI canvas integration."""
    
    def __init__(self, client_name: str = "verdandi_hall"):
        """Initialize JACK client connection."""
        try:
            self.client = jack.Client(client_name)
            self.client.activate()
            logger.info(f"JACK client '{client_name}' activated")
        except jack.JackError as e:
            logger.error(f"Failed to create JACK client: {e}")
            raise
    
    def get_ports(self, is_output: Optional[bool] = None, 
                  is_audio: bool = False, is_midi: bool = False) -> List[str]:
        """
        Get list of port names.
        
        Args:
            is_output: If True, return only output ports. If False, only input ports.
                      If None, return all ports.
            is_audio: If True, include only audio ports
            is_midi: If True, include only MIDI ports
        
        Returns:
            List of port names (full names like "client:port")
        """
        try:
            # Get all ports first
            all_ports = self.client.get_ports()
            
            # Filter based on criteria
            result = []
            for port in all_ports:
                # Check output/input
                if is_output is True and not port.is_output:
                    continue
                if is_output is False and not port.is_input:
                    continue
                
                # Check audio/MIDI
                if is_audio and not port.is_audio:
                    continue
                if is_midi and not port.is_midi:
                    continue
                
                result.append(port.name)
            
            return result
        except Exception as e:
            logger.error(f"Error getting ports: {e}")
            return []
    
    def get_all_connections(self) -> Dict[str, List[str]]:
        """
        Get all connections in the JACK graph.
        
        Returns:
            Dict mapping output port name to list of connected input port names.
            Example: {"system:capture_1": ["client:input_1", "client:input_2"]}
        """
        connections = {}
        
        try:
            # Get all ports
            all_ports = self.client.get_ports()
            
            # For each output port, get its connections
            for port in all_ports:
                if port.is_output:
                    # Get what this output is connected to
                    try:
                        connected = self.client.get_all_connections(port)
                        if connected:
                            connections[port.name] = [p.name for p in connected]
                    except:
                        # Port might not have connections
                        pass
        
        except Exception as e:
            logger.error(f"Error getting connections: {e}")
        
        return connections
    
    def get_sample_rate(self) -> int:
        """Get current JACK sample rate."""
        try:
            return self.client.samplerate
        except Exception as e:
            logger.error(f"Error getting sample rate: {e}")
            return 48000  # Default fallback
    
    def get_buffer_size(self) -> int:
        """Get current JACK buffer size."""
        try:
            return self.client.blocksize
        except Exception as e:
            logger.error(f"Error getting buffer size: {e}")
            return 256  # Default fallback
    
    def connect_ports(self, output_port: str, input_port: str):
        """
        Connect an output port to an input port.
        
        Args:
            output_port: Full name of output port (e.g., "system:capture_1")
            input_port: Full name of input port (e.g., "client:input_1")
        """
        try:
            self.client.connect(output_port, input_port)
            logger.info(f"Connected {output_port} -> {input_port}")
        except jack.JackError as e:
            logger.error(f"Failed to connect {output_port} -> {input_port}: {e}")
            raise
    
    def disconnect_ports(self, output_port: str, input_port: str):
        """
        Disconnect an output port from an input port.
        
        Args:
            output_port: Full name of output port
            input_port: Full name of input port
        """
        try:
            self.client.disconnect(output_port, input_port)
            logger.info(f"Disconnected {output_port} -X- {input_port}")
        except jack.JackError as e:
            logger.error(f"Failed to disconnect {output_port} -X- {input_port}: {e}")
            raise
    
    def close(self):
        """Close the JACK client connection."""
        try:
            self.client.deactivate()
            self.client.close()
            logger.info("JACK client closed")
        except Exception as e:
            logger.error(f"Error closing JACK client: {e}")
