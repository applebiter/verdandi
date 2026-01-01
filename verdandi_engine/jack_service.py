"""
gRPC service implementation for JACK audio graph operations.
"""

import logging
import grpc
from typing import Optional

from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc

logger = logging.getLogger(__name__)


class JackServicer(verdandi_pb2_grpc.JackServiceServicer):
    """Implementation of JackService."""
    
    def __init__(self, jack_manager=None):
        """
        Initialize with optional jack_manager.
        If None, will attempt to create one when needed.
        """
        self.jack_manager = jack_manager
    
    def _ensure_jack_manager(self):
        """Lazy load jack manager if not provided."""
        if self.jack_manager is None:
            try:
                from verdandi_hall.widgets.jack_client_manager import JackClientManager
                self.jack_manager = JackClientManager("verdandi_daemon_jack")
            except Exception as e:
                logger.error(f"Failed to initialize JACK manager: {e}")
                return None
        return self.jack_manager
    
    def GetJackGraph(self, request, context):
        """Return current JACK graph state."""
        jack_mgr = self._ensure_jack_manager()
        if not jack_mgr:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("JACK manager not available")
            return verdandi_pb2.JackGraphResponse()
        
        try:
            # Get all ports grouped by client
            all_ports = jack_mgr.get_all_ports()
            
            # Group ports by client name
            clients_dict = {}
            for port in all_ports:
                # Port format is "client_name:port_name"
                if ':' in port:
                    client_name, port_name = port.split(':', 1)
                    if client_name not in clients_dict:
                        clients_dict[client_name] = {
                            'name': client_name,
                            'input_ports': [],
                            'output_ports': []
                        }
                    
                    is_output = jack_mgr.is_output_port(port)
                    is_midi = jack_mgr.is_midi_port(port)
                    
                    port_info = verdandi_pb2.JackPort(
                        name=port_name,
                        full_name=port,
                        is_midi=is_midi
                    )
                    
                    if is_output:
                        clients_dict[client_name]['output_ports'].append(port_info)
                    else:
                        clients_dict[client_name]['input_ports'].append(port_info)
            
            # Build client list
            clients = []
            for client_data in clients_dict.values():
                clients.append(verdandi_pb2.JackClient(
                    name=client_data['name'],
                    input_ports=client_data['input_ports'],
                    output_ports=client_data['output_ports']
                ))
            
            # Get all connections
            connections = []
            all_connections = jack_mgr.get_all_connections()
            for output_port, input_ports in all_connections.items():
                for input_port in input_ports:
                    connections.append(verdandi_pb2.JackConnection(
                        output_port=output_port,
                        input_port=input_port
                    ))
            
            # Get JACK settings
            sample_rate = jack_mgr.get_sample_rate()
            buffer_size = jack_mgr.get_buffer_size()
            
            return verdandi_pb2.JackGraphResponse(
                clients=clients,
                connections=connections,
                sample_rate=sample_rate,
                buffer_size=buffer_size
            )
            
        except Exception as e:
            logger.error(f"Failed to get JACK graph: {e}", exc_info=True)
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to query JACK: {str(e)}")
            return verdandi_pb2.JackGraphResponse()
    
    def ConnectPorts(self, request, context):
        """Connect two JACK ports."""
        jack_mgr = self._ensure_jack_manager()
        if not jack_mgr:
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message="JACK manager not available"
            )
        
        try:
            jack_mgr.connect_ports(request.output_port, request.input_port)
            return verdandi_pb2.PortOperationResponse(
                success=True,
                message=f"Connected {request.output_port} -> {request.input_port}"
            )
        except Exception as e:
            logger.error(f"Failed to connect ports: {e}")
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message=str(e)
            )
    
    def DisconnectPorts(self, request, context):
        """Disconnect two JACK ports."""
        jack_mgr = self._ensure_jack_manager()
        if not jack_mgr:
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message="JACK manager not available"
            )
        
        try:
            jack_mgr.disconnect_ports(request.output_port, request.input_port)
            return verdandi_pb2.PortOperationResponse(
                success=True,
                message=f"Disconnected {request.output_port} -> {request.input_port}"
            )
        except Exception as e:
            logger.error(f"Failed to disconnect ports: {e}")
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message=str(e)
            )
