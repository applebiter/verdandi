"""
Verdandi Rune - CLI entry point.
"""

import sys
import argparse
import structlog

from verdandi_codex.config import VerdandiConfig
from verdandi_codex.database import Database


logger = structlog.get_logger()


def cmd_status(args):
    """Show node status."""
    config = VerdandiConfig.load()
    
    print("Verdandi Node Status")
    print("=" * 50)
    print(f"Node ID:         {config.node.node_id}")
    print(f"Hostname:        {config.node.hostname}")
    print(f"Display Name:    {config.node.display_name or '(not set)'}")
    print(f"Personality:     {config.node.personality_name or '(not set)'}")
    print(f"\nDaemon:")
    print(f"  Host:          {config.daemon.grpc_host}")
    print(f"  Port:          {config.daemon.grpc_port}")
    print(f"  mDNS:          {'enabled' if config.daemon.enable_mdns else 'disabled'}")
    print(f"\nDatabase:")
    print(f"  Host:          {config.database.host}")
    print(f"  Port:          {config.database.port}")
    print(f"  Database:      {config.database.database}")
    
    # Test database connection
    try:
        db = Database(config.database)
        print(f"  Status:        ✓ Connected")
    except Exception as e:
        print(f"  Status:        ✗ Error: {e}")


def cmd_init_db(args):
    """Initialize database schema."""
    from verdandi_codex.db_init import init_database
    
    if args.drop:
        confirm = input("⚠️  This will DROP ALL TABLES. Are you sure? (yes/no): ")
        if confirm.lower() != "yes":
            print("Aborted.")
            return
    
    init_database(drop_existing=args.drop)


def cmd_config(args):
    """Show or edit configuration."""
    config = VerdandiConfig.load()
    
    if args.edit:
        config_file = VerdandiConfig.get_config_file()
        import os
        editor = os.getenv("EDITOR", "nano")
        os.system(f"{editor} {config_file}")
    else:
        import yaml
        print(yaml.dump(config.to_dict(), default_flow_style=False, sort_keys=False))


def cmd_certs(args):
    """Manage certificates."""
    from verdandi_codex.crypto import NodeCertificateManager
    
    config = VerdandiConfig.load()
    cert_manager = NodeCertificateManager()
    
    if args.init:
        # Initialize certificates
        created = cert_manager.ensure_node_certificate(
            config.node.node_id,
            config.node.hostname,
        )
        if created:
            print("✓ Certificates created successfully")
        else:
            print("✓ Certificates already exist")
        
        paths = cert_manager.get_certificate_paths()
        print(f"\nCA Certificate:   {paths['ca_cert']}")
        print(f"Node Certificate: {paths['node_cert']}")
        print(f"Node Key:         {paths['node_key']}")
    
    elif args.show:
        paths = cert_manager.get_certificate_paths()
        fingerprint = cert_manager.get_certificate_fingerprint()
        
        print("Certificate Status")
        print("=" * 50)
        print(f"CA Certificate:   {paths['ca_cert']}")
        print(f"Node Certificate: {paths['node_cert']}")
        print(f"Node Key:         {paths['node_key']}")
        print(f"\nFingerprint:      {fingerprint or '(not found)'}")


def cmd_nodes(args):
    """List nodes in the fabric."""
    from verdandi_codex.database import Database
    from verdandi_codex.models import Node
    
    config = VerdandiConfig.load()
    
    try:
        db = Database(config.database)
        session = db.get_session()
        
        nodes = session.query(Node).order_by(Node.hostname).all()
        
        if not nodes:
            print("No nodes registered yet.")
            print("\nHint: Start verdandi-engine to discover nodes via mDNS")
            return
        
        print(f"Registered Nodes ({len(nodes)})")
        print("=" * 80)
        
        for node in nodes:
            status_symbol = "●" if node.status == "online" else "○"
            print(f"\n{status_symbol} {node.hostname} ({node.display_name})")
            print(f"  Node ID:  {node.node_id}")
            print(f"  Address:  {node.ip_last_seen}:{node.daemon_port}")
            print(f"  Status:   {node.status}")
            print(f"  Last Seen: {node.last_seen_at}")
        
        session.close()
        
    except Exception as e:
        print(f"Error: {e}")


def cmd_links(args):
    """Manage fabric links."""
    from verdandi_codex.database import Database
    from verdandi_codex.models import FabricLink, Node
    
    config = VerdandiConfig.load()
    
    try:
        db = Database(config.database)
        session = db.get_session()
        
        if args.create_audio:
            # Create audio link via gRPC
            import grpc
            import json
            from verdandi_codex.proto import verdandi_pb2, verdandi_pb2_grpc
            
            if not args.node_a or not args.node_b or not args.host:
                print("Error: --node-a, --node-b, and --host are required")
                return
            
            # Load TLS credentials
            import os
            config_dir = os.path.expanduser('~/.config/verdandi')
            with open(f'{config_dir}/certificates/ca.crt', 'rb') as f:
                ca_cert = f.read()
            with open(f'{config_dir}/certificates/node.crt', 'rb') as f:
                client_cert = f.read()
            with open(f'{config_dir}/certificates/node.key', 'rb') as f:
                client_key = f.read()
            
            credentials = grpc.ssl_channel_credentials(
                root_certificates=ca_cert,
                private_key=client_key,
                certificate_chain=client_cert
            )
            
            channel = grpc.secure_channel(f'localhost:{config.daemon.grpc_port}', credentials)
            stub = verdandi_pb2_grpc.FabricGraphServiceStub(channel)
            
            # Create the link
            response = stub.CreateAudioLink(verdandi_pb2.CreateAudioLinkRequest(
                node_a_id=args.node_a,
                node_b_id=args.node_b,
                params_json=json.dumps({
                    'remote_host': args.host,
                    'remote_port': args.port,
                    'channels': args.channels,
                    'sample_rate': args.sample_rate,
                    'buffer_size': args.buffer_size
                }),
                create_voice_cmd_bundle=False
            ))
            
            if response.success:
                print(f"✓ Audio link created successfully")
                print(f"  Link ID: {response.link_id}")
                print(f"  {response.message}")
            else:
                print(f"✗ Failed to create audio link")
                print(f"  {response.message}")
            
            channel.close()
            return
        
        if args.list or not args.create_audio:
            links = session.query(FabricLink).all()
            
            if not links:
                print("No links defined in fabric graph.")
                return
            
            print(f"Fabric Links ({len(links)})")
            print("=" * 80)
            
            for link in links:
                # Get node hostnames
                node_a = session.query(Node).filter_by(node_id=link.node_a_id).first()
                node_b = session.query(Node).filter_by(node_id=link.node_b_id).first()
                
                node_a_name = node_a.hostname if node_a else str(link.node_a_id)[:8]
                node_b_name = node_b.hostname if node_b else str(link.node_b_id)[:8]
                
                print(f"\n[{link.link_type.value}] {node_a_name} ↔ {node_b_name}")
                print(f"  Link ID:  {link.link_id}")
                print(f"  Status:   {link.status.value}")
                print(f"  Bundles:  {len(link.bundles)}")
                
                for bundle in link.bundles:
                    print(f"    • {bundle.name} ({bundle.channels}ch, {bundle.directionality.value})")
        
        session.close()
        
    except Exception as e:
        print(f"Error: {e}")


def main():
    """Main CLI entry point."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    
    parser = argparse.ArgumentParser(
        description="Verdandi Rune - CLI for Verdandi operations"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Status command
    parser_status = subparsers.add_parser("status", help="Show node status")
    parser_status.set_defaults(func=cmd_status)
    
    # Init-db command
    parser_init_db = subparsers.add_parser("init-db", help="Initialize database schema")
    parser_init_db.add_argument(
        "--drop",
        action="store_true",
        help="Drop existing tables (DESTRUCTIVE)",
    )
    parser_init_db.set_defaults(func=cmd_init_db)
    
    # Config command
    parser_config = subparsers.add_parser("config", help="Show or edit configuration")
    parser_config.add_argument(
        "--edit",
        action="store_true",
        help="Edit configuration file in $EDITOR",
    )
    parser_config.set_defaults(func=cmd_config)
    
    # Certs command
    parser_certs = subparsers.add_parser("certs", help="Manage certificates")
    parser_certs.add_argument(
        "--init",
        action="store_true",
        help="Initialize/create certificates",
    )
    parser_certs.add_argument(
        "--show",
        action="store_true",
        help="Show certificate information",
    )
    parser_certs.set_defaults(func=cmd_certs)
    
    # Nodes command
    parser_nodes = subparsers.add_parser("nodes", help="List registered nodes")
    parser_nodes.set_defaults(func=cmd_nodes)
    
    # Links command
    parser_links = subparsers.add_parser("links", help="Manage fabric links")
    parser_links.add_argument(
        "--list",
        action="store_true",
        help="List all links",
    )
    parser_links.add_argument(
        "--create-audio",
        action="store_true",
        help="Create an audio link",
    )
    parser_links.add_argument(
        "--node-a",
        type=str,
        help="Source node ID (or hostname)",
    )
    parser_links.add_argument(
        "--node-b",
        type=str,
        help="Target node ID (or hostname)",
    )
    parser_links.add_argument(
        "--host",
        type=str,
        help="Target host IP address",
    )
    parser_links.add_argument(
        "--port",
        type=int,
        default=4464,
        help="Target port (default: 4464)",
    )
    parser_links.add_argument(
        "--channels",
        type=int,
        default=2,
        help="Number of audio channels (default: 2)",
    )
    parser_links.add_argument(
        "--sample-rate",
        type=int,
        default=48000,
        help="JACK sample rate in Hz - must match all nodes (default: 48000)",
    )
    parser_links.add_argument(
        "--buffer-size",
        type=int,
        default=128,
        help="JACK buffer size in frames - must match all nodes (default: 128)",
    )
    parser_links.set_defaults(func=cmd_links)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    try:
        args.func(args)
        return 0
    except Exception as e:
        logger.error("command_failed", command=args.command, error=str(e), exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
