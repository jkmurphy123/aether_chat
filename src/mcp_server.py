import asyncio
from mcp.server.fastmcp import FastMCP
from typing import Literal
import time
import sys

# --- Google Generative AI SDK Imports (for tool definition) ---
# Import the main genai client library
from google import genai

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

_mock_display = MockDisplayManager()
_mock_mqtt = MockMQTTClient()


_default_pi_id_for_global_mcp = "pi1"
_temp_pi_id_for_global_mcp = _default_pi_id_for_global_mcp

if __name__ == "__main__":
    if len(sys.argv) > 1:
        _temp_pi_id_for_global_mcp = sys.argv[1]

# Define the global 'mcp' instance here.
mcp = FastMCP(
    name=f"pi-chatbot-{_temp_pi_id_for_global_mcp}-server",
    instructions=(
        f"This server controls Raspberry Pi {_temp_pi_id_for_global_mcp}. "
        "It can display messages on its HDMI screen and send messages to another Pi "
        "via MQTT. It can also provide status about its operational mode and the "
        "current conversation topic."
    )
)

class MCPServerManager:
    def __init__(self, pi_id: str, display_manager, mqtt_client):
        self.pi_id = pi_id
        self.display_manager = display_manager
        self.mqtt_client = mqtt_client
        
        self.mcp = mcp # Reference to the global FastMCP instance

        self.genai_callable_tools_map = {}

        @mcp.tool()
        async def _display_message(message: str) -> str:
            """
            Displays a text message on this Raspberry Pi's HDMI screen.

            Args:
                message (str): The text message to display.
            Returns:
                str: A confirmation message.
            """
            self.display_manager.display_message(message)
            return "Message displayed successfully."
        self.mcp.add_tool(_display_message)
        self.genai_callable_tools_map[_display_message.__name__] = _display_message


        @mcp.tool()
        async def _send_chat_message_to_other_pi(
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
            if target_pi_id == self.pi_id:
                return f"Error: Cannot send message to self ({self.pi_id})."
            
            self.mqtt_client.publish_chat_message(target_pi_id, message)
            return f"Message sent to {target_pi_id}."
        self.mcp.add_tool(_send_chat_message_to_other_pi)
        self.genai_callable_tools_map[_send_chat_message_to_other_pi.__name__] = _send_chat_message_to_other_pi


        @mcp.tool()
        async def _get_pi_status(query_pi_id: Literal["self", "other"]) -> dict:
            """
            Retrieves the current status of this Pi or the other Pi.

            Args:
                query_pi_id (Literal["self", "other"]): Whether to get status for 'self' or the 'other' Pi.
            Returns:
                dict: A dictionary containing status information.
            """
            status = {"pi_id": self.pi_id}
            status['mode'] = "unknown" # Placeholder - update this from main app state later
            status['online'] = True # Placeholder

            if query_pi_id == "other":
                other_id = "pi1" if self.pi_id == "pi2" else "pi2"
                status['other_pi_id'] = other_id
                status['other_pi_online'] = self.mqtt_client.is_other_pi_online(other_id)
            else:
                status['current_chat_topic'] = "unknown"

            return status
        self.mcp.add_tool(_get_pi_status)
        self.genai_callable_tools_map[_get_pi_status.__name__] = _get_pi_status


        @mcp.tool()
        async def _broadcast_chat_topic(topic: str) -> str:
            """
            Broadcasts the current conversation topic to all connected Raspberry Pis.
            This helps align context across devices.

            Args:
                topic (str): The current topic of discussion.
            Returns:
                str: A confirmation message.
            """
            self.mqtt_client.publish_current_chat_topic(topic)
            return "Chat topic broadcasted."
        self.mcp.add_tool(_broadcast_chat_topic)
        self.genai_callable_tools_map[_broadcast_chat_topic.__name__] = _broadcast_chat_topic


    def get_all_genai_callable_tools(self) -> list:
        """Returns a list of all genai-decorated callable tool functions."""
        return list(self.genai_callable_tools_map.values())

        # print(f"MCP Server for Pi '{self.pi_id}' (managed by MCPServerManager) initialized with tools.")
        # The above print statement should be outside the _register_tools method if it was there before.

    def run_server(self):
        """
        Runs the MCP server using the stdio transport.
        Note: This blocks. In main.py, you'd typically run this in a separate thread/task.
        """
        # This will call the instance-specific mcp object's run method
        print(f"Starting MCP server '{self.mcp.name}' with stdio transport...")
        self.mcp.run(transport='stdio')
        print(f"MCP server '{self.mcp.name}' stopped.")

# --- Mock objects (moved outside class, but only used in __main__) ---
_mock_display = MockDisplayManager()
_mock_mqtt = MockMQTTClient()

# --- Global FastMCP instance definition (removed and moved inside MCPServerManager) ---
# The 'mcp' object is now an instance attribute, NOT a global.
# This means `mcp dev src/mcp_server.py:mcp` will FAIL directly.
# To test with `mcp dev`, you would need to export the instance or use a different test harness.
# For now, we prioritize main.py working.

# --- Handling for `mcp dev` and direct execution (adjusted) ---
# This block is now ONLY for independent test usage if you were to run this script directly.
# It does NOT affect how main.py uses MCPServerManager.
if __name__ == "__main__":
    import sys
    my_pi_id = sys.argv[1] if len(sys.argv) > 1 else "pi1"

    # Instantiate MCPServerManager with mocks for direct testing
    mcp_server_manager_test = MCPServerManager(
        pi_id=my_pi_id,
        display_manager=_mock_display,
        mqtt_client=_mock_mqtt
    )

    print("\n--- MCP Server Test Instance Ready ---")
    print("This script is now configured to create an MCP server instance.")
    print("To test it with `mcp dev`, you need to expose the instance:")
    print(f"  Instead of `mcp dev src/mcp_server.py:mcp`, you might need to manually connect")
    print(f"  or export a global variable for `mcp dev` to pick up.")
    print(f"  For a quick test, you can add `global mcp_instance_for_dev_test; mcp_instance_for_dev_test = mcp_server_manager_test.mcp`")
    print(f"  after creating mcp_server_manager_test, then run `mcp dev -m src.mcp_server`.")
    print("Press Ctrl+C to stop this terminal if you ran it via python directly.")

    # If you want to run the MCP server directly from this file (for direct stdio connection),
    # uncomment the line below. This will block.
    # asyncio.run(mcp_server_manager_test.run_server())