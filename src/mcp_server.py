import asyncio
from mcp.server.fastmcp import FastMCP
from typing import Literal
import time

# --- Mock objects for independent testing (remain the same) ---
class MockDisplayManager:
    def display_message(self, message, *args, **kwargs):
        print(f"[Mock Display] {message}")
    def display_screensaver_text(self, text):
        print(f"[Mock Display Screensaver] {text}")
    def update_display(self): pass
    def quit(self): pass

class MockMQTTClient:
    def __init__(self):
        self.messages_sent = []
        self.online_status = {"pi1": (time.time(), True), "pi2": (time.time(), True)}
    def publish_chat_message(self, target_pi_id, message):
        self.messages_sent.append({"target": target_pi_id, "message": message})
        print(f"[Mock MQTT] Published to {target_pi_id}: {message}")
    def publish_status(self, is_online):
        print(f"[Mock MQTT] My status: {'online' if is_online else 'offline'}")
    def publish_current_chat_topic(self, topic):
        print(f"[Mock MQTT] Broadcasted topic: {topic}")
    def is_other_pi_online(self, other_pi_id: str) -> bool:
        return self.online_status.get(other_pi_id, (0, False))[1]

# --- Create mock instances globally for testing with mcp dev ---
_mock_display = MockDisplayManager()
_mock_mqtt = MockMQTTClient()


# --- Define the global FastMCP instance ( conditionally based on arguments for mcp dev) ---
# This needs to be set up so mcp dev can find it.

# Default PI ID for standalone run or if mcp dev doesn't provide args
_default_pi_id_for_dev_test = "pi1"

# The 'mcp dev' command can pass arguments via '--args'.
# We need to parse sys.argv to get the PI_ID if provided by mcp dev.
import sys
# Check if running from mcp dev with --args. sys.argv[0] is the script name.
# The first arg after script name would be the pi_id.
# This assumes mcp dev passes it cleanly.
if len(sys.argv) > 1 and sys.argv[0].endswith('mcp_server.py'): # Basic check if running this script directly or via mcp dev
    # This might be tricky as mcp dev might pass args differently.
    # A safer approach is to define mcp later after we know the pi_id
    pass # We'll define 'mcp' after parsing args below

class MCPServerManager:
    def __init__(self, pi_id: str, display_manager, mqtt_client):
        """
        Initializes the MCP server for this Raspberry Pi.
        This class is still useful for encapsulating the tools and state management
        within your main application loop.
        """
        self.pi_id = pi_id
        self.display_manager = display_manager
        self.mqtt_client = mqtt_client
        
        # When MCPServerManager is instantiated (likely in main.py),
        # it will register its tools with the global `mcp` instance.
        # The tools will "close over" the real display_manager and mqtt_client.
        self._register_tools(self.pi_id, self.display_manager, self.mqtt_client)
        print(f"MCP Server for Pi '{self.pi_id}' (managed by MCPServerManager) initialized with tools.")


    def _register_tools(self, pi_id, display_manager, mqtt_client):
        """Registers all the tools that the LLM can call using the global 'mcp' instance."""
        # Clear existing tools to avoid duplicates if this is called multiple times
        # though FastMCP might handle this internally or it's not strictly necessary.
        # This explicit re-registration is mainly for the mcp dev scenario.
        # In a real app, tools might be registered once at global scope or on init.
        # FastMCP's @tool decorator registers directly to the mcp instance it's called on.
        # If mcp is already defined globally, subsequent @mcp.tool() calls will add to it.

        @mcp.tool()
        async def display_message(message: str) -> str:
            """
            Displays a text message on this Raspberry Pi's HDMI screen.

            Args:
                message (str): The text message to display.
            Returns:
                str: A confirmation message.
            """
            print(f"[MCP Tool ({pi_id})] Displaying message: {message[:50]}...")
            display_manager.display_message(message)
            return "Message displayed successfully."

        @mcp.tool()
        async def send_chat_message_to_other_pi(
            target_pi_id: Literal["pi1", "pi2"],
            message: str
        ) -> str:
            """
            Sends a chat message to the other Raspberry Pi via MQTT.
            The message will be processed by the other Pi's AI.

            Args:
                target_pi_id (Literal["pi1", "pi2"]): The ID of the target Raspberry Pi.
                                                        Must be "pi1" or "pi2".
                message (str): The chat message to send.
            Returns:
                str: A confirmation message indicating if the message was sent.
            """
            if target_pi_id == pi_id:
                return f"Error: Cannot send message to self ({pi_id})."
            
            print(f"[MCP Tool ({pi_id})] Sending message to {target_pi_id}: {message[:50]}...")
            mqtt_client.publish_chat_message(target_pi_id, message)
            return f"Message sent to {target_pi_id}."

        @mcp.tool()
        async def get_pi_status(query_pi_id: Literal["self", "other"]) -> dict:
            """
            Retrieves the current status of this Pi or the other Pi.

            Args:
                query_pi_id (Literal["self", "other"]): Whether to get status for 'self' or the 'other' Pi.
            Returns:
                dict: A dictionary containing status information (e.g., {"mode": "idle", "online": true}).
                      For 'other', it will indicate if the other Pi is detected as online.
            """
            status = {"pi_id": pi_id}
            status['mode'] = "unknown" # Placeholder
            status['online'] = True # Placeholder (this pi is always online if server is running)

            if query_pi_id == "other":
                other_id = "pi1" if pi_id == "pi2" else "pi2"
                status['other_pi_id'] = other_id
                status['other_pi_online'] = mqtt_client.is_other_pi_online(other_id)
            else:
                status['current_chat_topic'] = "unknown" # Placeholder for now

            print(f"[MCP Tool ({pi_id})] Getting status for {query_pi_id}: {status}")
            return status

        @mcp.tool()
        async def broadcast_chat_topic(topic: str) -> str:
            """
            Broadcasts the current conversation topic to all connected Raspberry Pis.
            This helps align context across devices.

            Args:
                topic (str): The current topic of discussion.
            Returns:
                str: A confirmation message.
            """
            print(f"[MCP Tool ({pi_id})] Broadcasting topic: {topic}")
            mqtt_client.publish_current_chat_topic(topic)
            return "Chat topic broadcasted."

    def run_server(self):
        """Runs the MCP server using the stdio transport."""
        print(f"Starting MCP server '{mcp.name}' with stdio transport...")
        # This will call the global 'mcp' instance's run method
        mcp.run(transport='stdio')
        print(f"MCP server '{mcp.name}' stopped.")

# --- Handling for `mcp dev` and direct execution ---
# This block handles how the global 'mcp' object is created.
# It checks if an argument (presumably the pi_id) is passed.
_temp_pi_id_for_global_mcp = _default_pi_id_for_dev_test

if __name__ == "__main__":
    # When running directly: python src/mcp_server.py pi1
    # sys.argv will be ['src/mcp_server.py', 'pi1']
    if len(sys.argv) > 1:
        _temp_pi_id_for_global_mcp = sys.argv[1]

# Now, define the global 'mcp' instance *after* we've determined the pi_id
mcp = FastMCP(
    name=f"pi-chatbot-{_temp_pi_id_for_global_mcp}-server",
    instructions=(
        f"This server controls Raspberry Pi {_temp_pi_id_for_global_mcp}. "
        "It can display messages on its HDMI screen and send messages to another Pi "
        "via MQTT. It can also provide status about its operational mode and the "
        "current conversation topic."
    )
)

# Instantiate MCPServerManager once to register tools with the global `mcp` instance
# using the mock objects for dev testing.
# This ensures that when 'mcp dev' imports this file, the 'mcp' object is fully
# configured with tools.
_mcp_instance_for_dev_test = MCPServerManager(
    pi_id=_temp_pi_id_for_global_mcp,
    display_manager=_mock_display,
    mqtt_client=_mock_mqtt
)

print("\n--- MCP Server Ready for Connections (for 'mcp dev' testing) ---")
print(f"To test, run in a separate terminal (with venv active, in project root):")
print(f"  mcp dev src/mcp_server.py:mcp --args {_temp_pi_id_for_global_mcp}")
print("   (Replace 'pi1' or 'pi2' if you are trying different IDs.)")
print("Or configure Claude Desktop to connect to this server.")
print("Press Ctrl+C to stop this terminal if you ran it via python directly.")

# If you run this script directly (e.g., `python src/mcp_server.py`),
# it will simply set up the global 'mcp' instance and register tools.
# The 'mcp.run()' call will be handled by the 'mcp dev' command when it imports this module.
# If you wanted to run the server directly from `python src/mcp_server.py`,
# you would add `mcp.run(transport='stdio')` to the `if __name__ == "__main__":` block,
# but 'mcp dev' is the preferred way for inspection.