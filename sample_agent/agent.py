"""
Customer Service Agent - AgentCore Runtime

Provides customer service functionality including order history,
customer scoring, product recommendations, and service status.
"""

import os
import json
import time
import traceback
from typing import Dict, Any
from datetime import datetime

# AgentCore Runtime SDK
from bedrock_agentcore.runtime import BedrockAgentCoreApp

import pandas as pd
import numpy as np
import requests

from helper_module import calculate_ratio, process_calculation

# Initialize AgentCore app
app = BedrockAgentCoreApp()


class CustomerServiceAgent:
    """Customer service agent"""
    
    def __init__(self):
        self.agent_name = "CustomerServiceBot"
        print(f"✅ Agent initialized: {self.agent_name}")
    
    def process_inquiry(self, customer_message: str) -> Dict[str, Any]:
        """Process customer inquiry based on message content"""
        
        if not customer_message:
            return {"error": "Empty message"}
        
        message_lower = customer_message.lower()
        
        if "order" in message_lower or "history" in message_lower:
            return self._get_order_history(customer_message)
        
        elif "score" in message_lower or "rating" in message_lower:
            return self._calculate_customer_score(customer_message)
        
        elif "recommend" in message_lower or "suggest" in message_lower:
            return self._get_recommendations(customer_message)
        
        elif "status" in message_lower or "check" in message_lower:
            return self._check_service_status(customer_message)
        
        elif "test" in message_lower and "module" in message_lower:
            return self._test_imported_module(customer_message)
        
        else:
            # Default response
            return {
                "response": "I can help you with: order history, customer ratings, recommendations, or service status.",
                "agent": self.agent_name,
                "timestamp": datetime.now().isoformat()
            }
    
    def _get_order_history(self, query: str) -> Dict[str, Any]:
        """Get order history"""
        
        df = pd.DataFrame({
            "order_id": ["ORD-001", "ORD-002"],
            "product": ["Laptop", "Mouse"],
            "amount": [1200.00, 25.00],
            "status": ["Delivered", "Shipped"]
        })
        
        new_order = {
            "order_id": "ORD-003",
            "product": "Keyboard",
            "amount": 75.00,
            "status": "Processing"
        }
        df = df.append(new_order, ignore_index=True)
        
        return {
            "response": "Order history retrieved successfully",
            "orders": df.to_dict('records'),
            "total_orders": len(df),
            "total_amount": float(df['amount'].sum()),
            "agent": self.agent_name,
            "timestamp": datetime.now().isoformat()
        }
    
    def _calculate_customer_score(self, query: str) -> Dict[str, Any]:
        """Calculate customer score"""
        
        purchase_count = 15
        avg_order_value = 250.50
        return_rate = 0.05
        
        customer_tier = np.int(purchase_count / 5)
        
        # Calculate score
        base_score = purchase_count * 10
        value_bonus = avg_order_value * 0.5
        return_penalty = return_rate * 100
        
        final_score = base_score + value_bonus - return_penalty
        
        return {
            "response": "Customer score calculated successfully",
            "customer_score": round(final_score, 2),
            "tier": customer_tier,
            "tier_name": ["Bronze", "Silver", "Gold", "Platinum"][min(customer_tier, 3)],
            "metrics": {
                "purchase_count": purchase_count,
                "avg_order_value": avg_order_value,
                "return_rate": return_rate
            },
            "agent": self.agent_name,
            "timestamp": datetime.now().isoformat()
        }
    
    def _get_recommendations(self, query: str) -> Dict[str, Any]:
        """Get product recommendations (simplified - no torch)"""
        
        products = {
            "Laptop Pro": 0.92,
            "Wireless Mouse": 0.85,
            "Mechanical Keyboard": 0.88,
            "USB-C Hub": 0.75,
            "Monitor 4K": 0.80
        }
        
        recommendations = [
            {"product": name, "similarity_score": score}
            for name, score in products.items()
        ]
        recommendations.sort(key=lambda x: x['similarity_score'], reverse=True)
        
        return {
            "response": "Product recommendations generated successfully",
            "recommendations": recommendations[:3],
            "total_products_analyzed": len(products),
            "agent": self.agent_name,
            "timestamp": datetime.now().isoformat()
        }
    
    def _check_service_status(self, query: str) -> Dict[str, Any]:
        """Check service status"""
        
        api_url = "https://api.example.com/status"
        response = requests.get(api_url, timeout=5)
        data = response.json()
        
        return {
            "response": "Service status checked successfully",
            "services": {
                "order_processing": {"status": "operational", "uptime": "99.9%"},
                "payment_gateway": {"status": "operational", "uptime": "99.8%"},
                "shipping_api": {"status": "operational", "uptime": "99.7%"},
                "inventory_system": {"status": "operational", "uptime": "99.9%"}
            },
            "overall_status": "All systems operational",
            "last_incident": "2025-11-01 14:30:00 UTC",
            "agent": self.agent_name,
            "timestamp": datetime.now().isoformat()
        }
    
    def _test_imported_module(self, query: str) -> Dict[str, Any]:
        """Test imported module"""
        
        result = process_calculation()
        
        return {
            "response": "Module test completed",
            "result": result,
            "agent": self.agent_name,
            "timestamp": datetime.now().isoformat()
        }


# AgentCore Runtime entrypoint
@app.entrypoint
def invoke(payload):
    """Main entrypoint for AgentCore Runtime"""
    
    try:
        # Extract user message
        user_message = payload.get("prompt", "")
        
        print(f"📨 Received message: {user_message}")
        
        # Initialize agent
        agent = CustomerServiceAgent()
        
        # Process inquiry
        result = agent.process_inquiry(user_message)
        
        print(f"✅ Response generated: {result.get('response', 'Success')}")
        
        # Return response in correct format
        return {
            "response": json.dumps(result, indent=2),
            "status": "success"
        }
        
    except Exception as e:
        # Get full traceback for debugging
        error_traceback = traceback.format_exc()
        error_type = type(e).__name__
        timestamp = datetime.now().isoformat()
        
        # Log error in CloudWatch-compatible JSON format
        # This matches the format the dashboard expects
        error_log = {
            "timestamp": timestamp,
            "level": "ERROR",
            "errorType": error_type,
            "errorMessage": str(e),
            "stackTrace": error_traceback.split('\n'),  # Array of strings
            "agent": "CustomerServiceBot"
        }
        
        # Print as JSON for CloudWatch structured logging
        print(json.dumps(error_log))
        
        return {
            "response": json.dumps({
                "error": str(e),
                "error_type": error_type,
                "traceback": error_traceback,
                "agent": "CustomerServiceBot",
                "timestamp": timestamp
            }, indent=2),
            "status": "error"
        }


# Main execution
if __name__ == "__main__":
    app.run()
