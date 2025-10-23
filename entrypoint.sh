#!/bin/bash
# Fix permissions for Raspberry Pi device files
chmod a+r /dev/vcio /dev/vchiq

# Start your main process
exec "$@"
