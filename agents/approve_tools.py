#!/usr/bin/env python3
"""
Simple MCP approval server that forwards approval requests to the main app
"""

from mcp.server.fastmcp import FastMCP
import requests
import json
import uuid
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create MCP server
mcp = FastMCP("approve-tools")

# check the 

# Main app URL
MAIN_APP_URL = os.getenv("MAIN_APP_URL")
PORT = os.getenv("PORT")

@mcp.tool()
async def permissions__approve(tool_name: str, input: dict, reason: str = "") -> dict:
    """
    Request approval for tool usage from Claude.
    
    This function forwards the approval request to the main app,
    which handles the frontend interaction.
    
    Args:
        tool_name: Name of the tool requesting approval
        input: Input parameters for the tool
        reason: Reason for the approval request
        
    Returns:
        dict with behavior:"allow"/"deny" and updated input
    """
    approval_id = str(uuid.uuid4())
    
    logger.info(f"Approval request {approval_id}: tool={tool_name}")
    
    try:
        # Send approval request to main app
        approval_request = {
            "approval_id": approval_id,
            "tool_name": tool_name,
            "input": input,
            "reason": reason
        }
        
        # MAIN_APP_URL = f"{request.host}:{PORT}"
        # logger.error(f"Approval request {approval_id}: MAIN_APP_URL: {MAIN_APP_URL}")

        response = requests.post(
            f"{MAIN_APP_URL}/api/approve_tools",
            json=approval_request,
            timeout=300  # 5 minute timeout
        )
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("approved"):
                logger.info(f"Approval {approval_id}: APPROVED")
                return {
                    "behavior": "allow",
                    "updatedInput": input,
                    "approval_id": approval_id
                }
            else:
                logger.info(f"Approval {approval_id}: DENIED - {result.get('reason', 'No reason provided')}")
                return {
                    "behavior": "deny",
                    "message": result.get("reason", "User denied the request"),
                    "approval_id": approval_id
                }
        else:
            logger.error(f"Approval {approval_id}: Server error {response.status_code}")
            return {
                "behavior": "deny",
                "message": f"Approval server error: {response.status_code}",
                "approval_id": approval_id
            }
            
    except requests.exceptions.Timeout:
        logger.error(f"Approval {approval_id}: Timeout")
        return {
            "behavior": "deny",
            "message": "Approval request timed out (5 minutes)",
            "approval_id": approval_id
        }
    except requests.exceptions.ConnectionError:
        logger.error(f"Approval {approval_id}: Connection error")
        return {
            "behavior": "deny",
            "message": "Cannot connect to approval server",
            "approval_id": approval_id
        }
    except Exception as e:
        logger.error(f"Approval {approval_id}: Error - {e}")
        return {
            "behavior": "deny",
            "message": f"Approval system error: {str(e)}",
            "approval_id": approval_id
        }

if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run())