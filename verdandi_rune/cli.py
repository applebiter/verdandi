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
    """List registered nodes."""
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


def cmd_jacktrip(args):
    """Manage JackTrip hub state."""
    config = VerdandiConfig.load()
    db = Database(config.database)
    
    if args.clear_hub:
        from verdandi_codex.models.jacktrip import JackTripHub
        
        session = db.get_session()
        hub = session.query(JackTripHub).first()
        
        if hub:
            print(f"Clearing hub state: {hub.hub_hostname} (port {hub.hub_port})")
            session.delete(hub)
            session.commit()
            print("✓ Hub state cleared from database")
        else:
            print("No hub state in database")
        
        session.close()


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
    
    # JackTrip command
    parser_jacktrip = subparsers.add_parser("jacktrip", help="Manage JackTrip hub state")
    parser_jacktrip.add_argument(
        "--clear-hub",
        action="store_true",
        help="Clear stale hub state from database",
    )
    parser_jacktrip.set_defaults(func=cmd_jacktrip)
    
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
