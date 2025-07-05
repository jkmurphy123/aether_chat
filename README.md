# aether_chat
A python app for raspberry pi's to chat with each other over wifi.

The poject struture looks like this:

aether_chat/
├── .venv/
├── src/
│   ├── __init__.py
│   ├── main.py           # Main application loop, mode management
│   ├── mcp_server.py     # Defines and runs your MCP server, registers tools
│   ├── mqtt_client.py    # Handles MQTT connection, subscriptions, publishing
│   ├── display_manager.py # Manages HDMI output (text rendering, screensaver)
│   └── llm_interface.py  # Handles API calls to your cloud LLM
├── pyproject.toml        # For `uv` and project metadata
├── .env.example          # Template for environment variables (API keys, etc.)
└── README.md