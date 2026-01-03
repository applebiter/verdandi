"""
gRPC service implementation for JACK audio graph operations.
"""

import logging
import grpc
import jack
from typing import Optional

from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc

logger = logging.getLogger(__name__)


class JackServicer(verdandi_pb2_grpc.JackServiceServicer):
    """Implementation of JackService."""
    
    def __init__(self, jack_manager=None):
        """
        Initialize with optional jack_manager.
        The jack_manager parameter is ignored - we create our own JACK client.
        """
        self.jack_client = None
    
    def _ensure_jack_client(self):
        """Lazy load JACK client if not created."""
        if self.jack_client is None:
            try:
                self.jack_client = jack.Client("verdandi_grpc_jack_query")
                self.jack_client.activate()
            except Exception as e:
                logger.error(f"Failed to initialize JACK client: {e}")
                return None
        return self.jack_client
    
    def GetJackGraph(self, request, context):
        """Return current JACK graph state."""
        client = self._ensure_jack_client()
        if not client:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("JACK client not available")
            return verdandi_pb2.JackGraphResponse()
        
        try:
            # Get all ports
            all_ports = client.get_ports()
            logger.info(f"GetJackGraph: Found {len(all_ports)} total ports")
            output_ports = set(p.name for p in client.get_ports() if p.is_output)
            
            # Group ports by client name
            clients_dict = {}
            for port_obj in all_ports:
                port_name = port_obj.name
                
                # Port format is "client_name:port_name"
                if ':' not in port_name:
                    continue
                    
                client_name, port_short = port_name.split(':', 1)
                if client_name not in clients_dict:
                    clients_dict[client_name] = {
                        'name': client_name,
                        'input_ports': [],
                        'output_ports': []
                    }
                    logger.info(f"GetJackGraph: Found client '{client_name}'")
                
                # Check if port is output and if it's MIDI
                is_output = port_name in output_ports
                is_midi = port_obj.is_midi
                
                port_info = verdandi_pb2.JackPort(
                    name=port_short,
                    full_name=port_name,
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
            for port_obj in all_ports:
                if port_obj.is_output:
                    # Get connections from this output port
                    connected_ports = client.get_all_connections(port_obj)
                    for connected_port in connected_ports:
                        connections.append(verdandi_pb2.JackConnection(
                            output_port=port_obj.name,
                            input_port=connected_port.name
                        ))
            
            # Get JACK settings
            sample_rate = client.samplerate
            buffer_size = client.blocksize
            
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
        client = self._ensure_jack_client()
        if not client:
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message="JACK client not available"
            )
        
        try:
            logger.info(f"ConnectPorts: Attempting to connect '{request.output_port}' -> '{request.input_port}'")
            
            # Verify ports exist
            try:
                out_port = client.get_port_by_name(request.output_port)
                in_port = client.get_port_by_name(request.input_port)
                logger.info(f"  Output port exists: {out_port.name}, is_output={out_port.is_output}")
                logger.info(f"  Input port exists: {in_port.name}, is_input={out_port.is_input}")
            except Exception as port_err:
                logger.error(f"  Port lookup failed: {port_err}")
                return verdandi_pb2.PortOperationResponse(
                    success=False,
                    message=f"Port not found: {port_err}"
                )
            
            # Attempt connection
            client.connect(request.output_port, request.input_port)
            logger.info(f"  Connection successful")
            return verdandi_pb2.PortOperationResponse(
                success=True,
                message=f"Connected {request.output_port} -> {request.input_port}"
            )
        except Exception as e:
            logger.error(f"  Failed to connect ports: {e}")
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message=str(e)
            )
    
    def DisconnectPorts(self, request, context):
        """Disconnect two JACK ports."""
        client = self._ensure_jack_client()
        if not client:
            return verdandi_pb2.PortOperationResponse(
                success=False,
                message="JACK client not available"
            )
        
        try:
            client.disconnect(request.output_port, request.input_port)
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
