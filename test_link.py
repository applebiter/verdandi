#!/usr/bin/env python3
"""Quick test script to create an audio link."""
import grpc
from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc
import json

def create_audio_link():
    # Load certificates for TLS
    with open('/home/sysadmin/.config/verdandi/certificates/ca.crt', 'rb') as f:
        ca_cert = f.read()
    
    credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)
    channel = grpc.secure_channel('localhost:50051', credentials)
    stub = verdandi_pb2_grpc.FabricGraphServiceStub(channel)
    
    # Create audio link from onyx to green
    response = stub.CreateAudioLink(verdandi_pb2.CreateAudioLinkRequest(
        node_a_id='2bd5c01c-002b-406e-ad15-edc33dc0b459',  # onyx
        node_b_id='666df9df-ef76-430b-b865-f22245910d00',  # green  
        params_json=json.dumps({
            'remote_host': '192.168.32.5',
            'remote_port': 4464,
            'channels': 2
        }),
        create_voice_cmd_bundle=False
    ))
    
    print(f'Success: {response.success}')
    print(f'Message: {response.message}')
    if response.link_id:
        print(f'Link ID: {response.link_id}')

if __name__ == '__main__':
    create_audio_link()
