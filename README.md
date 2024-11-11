# DraXon OCULUS - Discord Management System v2.0.5

A comprehensive Discord bot designed for DraXon (DraXon Industries) that handles server management, RSI integration, and automated organizational tasks. OCULUS (Organizational Command & Unified Leadership Implementation System) provides advanced management and monitoring capabilities.

## Features

### Server Management
- Automated channel creation and management
- Dynamic channel statistics
- Server backup and restore functionality
- Role management system
- Automated role verification

### RSI Integration
- Account linking with RSI handles
- Organization member tracking
- Member verification system
- Main/Affiliate status tracking
- Member comparison tools
- Daily account link reminders
- Automated affiliate role management

### Status Monitoring
- RSI Platform status tracking
- Real-time incident monitoring
- Automated status updates
- Dedicated status channels

### Role Management
- Promotion/demotion system with updated hierarchy
  - Magnate (Highest)
  - Chairman
  - Executive
  - Team Leader
  - Employee
  - Applicant
  - Screening
- Automated role assignments
- Role verification based on org status
- Multi-channel notification system
- Permission management

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 15 or higher
- Redis 7 or higher
- Docker (optional)

## Installation

### Using Docker (Recommended)

1. Clone the repository:
```bash
git clone https://github.com/CaptainASIC/DraXon_OCULUS
cd DraXon
```

2. Copy and configure environment variables:
```bash
cp env/.env.example env/.env
# Edit env/.env with your configuration
```

3. Start the services:
```bash
docker-compose up -d
```

### Manual Installation

1. Clone the repository:
```bash
git clone https://github.com/CaptainASIC/DraXon_OCULUS
cd DraXon
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp env/.env.example env/.env
# Edit env/.env with your configuration
```

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the bot:
```bash
python bot.py
```

## Commands

### Basic Commands
- `/system-status` - Display current status of RSI systems
- `/draxon-link` - Link your RSI account with Discord
- `/draxon-org` - Display organization member list with roles
- `/draxon-compare` - Compare Discord members with RSI org members
- `/help` - Display all available commands

### Leadership Commands
- `/draxon-stats` - Display member statistics (Leadership)
- `/promote` - Promote a member (Leadership)
- `/demote` - Demote a member (Leadership)

### Management Commands
- `/refresh-channels` - Refresh channel information
- `/setup` - Configure bot channels and notifications
- `/force-check` - Check incidents and status
- `/draxon-backup` - Create server backup
- `/draxon-restore` - Restore from backup

## Database Structure

The system uses PostgreSQL for storing RSI member data and Redis for caching. The database includes:
- Member information
- Organization status
- Verification data
- Linking history
- Role change history

## New in v2.0.5

- Rebranded to DraXon OCULUS (Organizational Command & Unified Leadership Implementation System)
- Updated role hierarchy system
- Enhanced command feedback and error handling
- Improved performance and reliability
- Updated documentation and help system
- Bug fixes and stability improvements

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License 

This project is licensed under the GNU General Public License v3.0 (GPL-3.0). See the [LICENSE](LICENSE) file for details.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

## Contact

For questions or issues:
- GitHub Issues: [Create an issue](https://github.com/CaptainASIC/DraXon_OCULUS/issues)
- DraXon Discord: [Join our server](https://discord.gg/bjFZBRhw8Q)

Created by DraXon (DraXon Industries)
