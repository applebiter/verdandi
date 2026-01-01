#!/bin/bash
# Install verdandi-daemon systemd service
# Run this on each node

set -e

echo "Installing verdandi-daemon systemd service..."

cd /home/sysadmin/Programs/verdandi
git pull origin master

sudo cp packaging/verdandi-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable verdandi-daemon
sudo systemctl start verdandi-daemon

echo ""
echo "Service status:"
sudo systemctl status verdandi-daemon --no-pager -l

echo ""
echo "✓ verdandi-daemon service installed and started"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status verdandi-daemon   # Check status"
echo "  sudo systemctl restart verdandi-daemon  # Restart"
echo "  sudo systemctl stop verdandi-daemon     # Stop"
echo "  sudo journalctl -u verdandi-daemon -f   # View logs"
