# Cost Automation — Flask API Integration

Add these endpoints to `app.py` to expose the cost system via REST API.

## Quick Start

Add these routes to your Flask app:

```python
# In app.py, after other imports
from costs import (
    update_cost_rates, 
    get_cost_health_check,
    calculate_trade_charges,
    get_costs_config,
)
from cost_updater import get_cost_history, rollback_costs
from cost_notifications import get_unread_notifications, mark_notification_as_read

# ── Cost Management API Endpoints ────────────────────────────────────────────

@app.route('/api/costs/health', methods=['GET'])
@require_auth
def api_cost_health_check():
    """Get health status of cost system."""
    try:
        health = get_cost_health_check()
        return jsonify(health), 200
    except Exception as e:
        logger.error(f"Cost health check failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/costs/config', methods=['GET'])
@require_auth
def api_get_costs_config():
    """Get all current cost configuration grouped by category."""
    try:
        config = get_costs_config()
        return jsonify(config), 200
    except Exception as e:
        logger.error(f"Failed to get costs config: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/costs/calculate', methods=['POST'])
@require_auth
def api_calculate_trade_charges():
    """Calculate estimated charges for a trade."""
    try:
        data = request.get_json()
        
        # Validate input
        required = ['side', 'quantity', 'price']
        if not all(k in data for k in required):
            return jsonify({"error": f"Missing required fields: {required}"}), 400
        
        charges = calculate_trade_charges(
            side=data.get('side', 'BUY').upper(),
            quantity=int(data.get('quantity', 0)),
            price=float(data.get('price', 0)),
            product=data.get('product', 'CNC').upper(),
            segment=data.get('segment', 'CASH').upper(),
        )
        
        return jsonify(charges), 200
    except Exception as e:
        logger.error(f"Charge calculation failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/costs/history', methods=['GET'])
@require_auth
def api_cost_history():
    """Get historical cost values for a specific cost type."""
    try:
        cost_type = request.args.get('cost_type', 'brokerage_flat_per_order')
        days = int(request.args.get('days', 90))
        
        history = get_cost_history(cost_type, days=days)
        
        return jsonify({
            "cost_type": cost_type,
            "days": days,
            "records": history,
        }), 200
    except Exception as e:
        logger.error(f"Cost history retrieval failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/costs/manual-check', methods=['POST'])
@require_auth
def api_manual_cost_check():
    """Manually trigger a cost scrape and update (admin only)."""
    try:
        # Check if user is admin
        user = get_current_user()
        if not user or user.get('role') != 'admin':
            return jsonify({"error": "Admin access required"}), 403
        
        logger.info(f"Manual cost check triggered by {user.get('email')}")
        
        result = update_cost_rates()
        
        return jsonify({
            "triggered_by": user.get('email'),
            "result": result,
        }), 200
    except Exception as e:
        logger.error(f"Manual cost check failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/costs/rollback', methods=['POST'])
@require_auth
def api_rollback_cost():
    """Rollback a cost to previous value using audit log (admin only)."""
    try:
        # Check if user is admin
        user = get_current_user()
        if not user or user.get('role') != 'admin':
            return jsonify({"error": "Admin access required"}), 403
        
        data = request.get_json()
        audit_id = data.get('audit_id')
        
        if not audit_id:
            return jsonify({"error": "audit_id required"}), 400
        
        success, message = rollback_costs(int(audit_id))
        
        logger.warning(f"Rollback requested by {user.get('email')}: {message}")
        
        return jsonify({
            "success": success,
            "message": message,
            "performed_by": user.get('email'),
        }), 200 if success else 400
    except Exception as e:
        logger.error(f"Cost rollback failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/notifications/cost-updates', methods=['GET'])
@require_auth
def api_cost_notifications():
    """Get unread cost update notifications."""
    try:
        limit = int(request.args.get('limit', 10))
        
        notifications = get_unread_notifications(limit=limit)
        
        return jsonify({
            "count": len(notifications),
            "notifications": notifications,
        }), 200
    except Exception as e:
        logger.error(f"Failed to retrieve cost notifications: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@require_auth
def api_mark_notification_read(notification_id):
    """Mark a cost notification as read."""
    try:
        success = mark_notification_as_read(notification_id)
        
        return jsonify({
            "success": success,
            "notification_id": notification_id,
        }), 200 if success else 404
    except Exception as e:
        logger.error(f"Failed to mark notification as read: {e}")
        return jsonify({"error": str(e)}), 500
```

## Endpoint Reference

### 1. Health Check
```
GET /api/costs/health
Authorization: Bearer <token>

Response (200):
{
    "status": "healthy|warning|error",
    "last_update": "2026-07-31T12:00:00",
    "costs_tracked": 8,
    "recent_errors": [],
    "next_update_in": "~45 days"
}
```

### 2. Get Cost Configuration
```
GET /api/costs/config
Authorization: Bearer <token>

Response (200):
{
    "updated_at": "2026-07-31T12:00:00",
    "source": "Groww",
    "costs": {
        "brokerage": {
            "name": "Brokerage",
            "items": [
                {
                    "key": "brokerage_flat_per_order",
                    "value": 20.0,
                    "unit": "₹",
                    "description": "Flat brokerage per order"
                }
            ]
        },
        "stt": {
            "name": "STT",
            "items": [...]
        },
        ...
    },
    "total_tracked": 8
}
```

### 3. Calculate Trade Charges
```
POST /api/costs/calculate
Authorization: Bearer <token>
Content-Type: application/json

Body:
{
    "side": "BUY",              # Required: "BUY" or "SELL"
    "quantity": 10,             # Required: Number of shares
    "price": 2500.0,            # Required: Price per share
    "product": "CNC",           # Optional: "CNC" (delivery) or "MIS" (intraday)
    "segment": "CASH"           # Optional: "CASH" or "DERIVATIVE"
}

Response (200):
{
    "turnover": 25000.0,
    "brokerage": 20.0,
    "stt": 0.0,
    "exchange_charge": 8.13,
    "sebi_fee": 0.08,
    "dp_charge": 0.0,
    "gst": 5.04,
    "total_charges": 33.24,
    "net_value": 25033.24
}
```

### 4. Get Cost History
```
GET /api/costs/history?cost_type=brokerage_flat_per_order&days=90
Authorization: Bearer <token>

Query Parameters:
  cost_type: (optional) Cost key to filter (default: brokerage_flat_per_order)
  days: (optional) Look back N days (default: 90)

Response (200):
{
    "cost_type": "brokerage_flat_per_order",
    "days": 90,
    "records": [
        {
            "date": "2026-07-31T12:00:00",
            "cost_type": "brokerage_flat_per_order",
            "old_value": 20.0,
            "new_value": 21.0,
            "changed": true,
            "percent_change": 5.0,
            "source_url": "https://groww.in/charges",
            "notes": "Updated via cost_scraper automation"
        }
    ]
}
```

### 5. Manual Cost Check (Admin Only)
```
POST /api/costs/manual-check
Authorization: Bearer <admin_token>
Content-Type: application/json

Response (200):
{
    "triggered_by": "admin@example.com",
    "result": {
        "success": true,
        "timestamp": "2026-07-31T12:00:00",
        "summary": {
            "costs_checked": 8,
            "costs_updated": 2,
            "costs_unchanged": 6,
            "suspicious_changes": [],
            "total_errors": 0
        }
    }
}

Response (403): {"error": "Admin access required"}
```

### 6. Rollback Cost (Admin Only)
```
POST /api/costs/rollback
Authorization: Bearer <admin_token>
Content-Type: application/json

Body:
{
    "audit_id": 123  # Required: ID from cost_audit_log table
}

Response (200):
{
    "success": true,
    "message": "Updated brokerage_flat_per_order: 21.0 → 20.0",
    "performed_by": "admin@example.com"
}

Response (400): 
{
    "success": false,
    "message": "Cannot rollback - no previous value in audit log",
    "performed_by": "admin@example.com"
}
```

### 7. Get Cost Notifications
```
GET /api/notifications/cost-updates?limit=10
Authorization: Bearer <token>

Query Parameters:
  limit: (optional) Max notifications to return (default: 10)

Response (200):
{
    "count": 2,
    "notifications": [
        {
            "id": 1,
            "type": "cost_update",
            "message": "2 trading costs updated",
            "data": {
                "type": "cost_update",
                "update_result": {...},
                "scrape_result": {...},
                "timestamp": "2026-07-31T12:00:00"
            },
            "created_at": "2026-07-31T12:00:00"
        }
    ]
}
```

### 8. Mark Notification as Read
```
POST /api/notifications/1/read
Authorization: Bearer <token>

Response (200):
{
    "success": true,
    "notification_id": 1
}

Response (404):
{
    "error": "Notification not found"
}
```

## Frontend Integration Examples

### React Hook: Fetch Cost Configuration
```jsx
// useCosts.js
import { useEffect, useState } from 'react';

export const useCosts = () => {
    const [costs, setCosts] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        fetch('/api/costs/config', {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        })
            .then(r => r.json())
            .then(setCosts)
            .catch(setError)
            .finally(() => setLoading(false));
    }, []);

    return { costs, loading, error };
};

// Component usage
function CostConfigPanel() {
    const { costs, loading } = useCosts();
    
    if (loading) return <div>Loading costs...</div>;
    
    return (
        <div>
            {costs && Object.entries(costs.costs).map(([cat, data]) => (
                <div key={cat}>
                    <h3>{data.name}</h3>
                    {data.items.map(item => (
                        <div key={item.key}>
                            {item.description}: {item.value}{item.unit}
                        </div>
                    ))}
                </div>
            ))}
        </div>
    );
}
```

### React Component: Calculate Charges
```jsx
import { useState } from 'react';

function ChargeCalculator() {
    const [charges, setCharges] = useState(null);
    const [formData, setFormData] = useState({
        side: 'BUY',
        quantity: 10,
        price: 2500,
        product: 'CNC',
    });

    const calculateCharges = async () => {
        const res = await fetch('/api/costs/calculate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('token')}`
            },
            body: JSON.stringify(formData),
        });
        const data = await res.json();
        setCharges(data);
    };

    return (
        <div>
            <input 
                placeholder="Quantity" 
                value={formData.quantity}
                onChange={e => setFormData({...formData, quantity: e.target.value})}
            />
            <input 
                placeholder="Price" 
                value={formData.price}
                onChange={e => setFormData({...formData, price: e.target.value})}
            />
            <button onClick={calculateCharges}>Calculate Charges</button>
            
            {charges && (
                <div>
                    <p>Turnover: ₹{charges.turnover.toFixed(2)}</p>
                    <p>Brokerage: ₹{charges.brokerage.toFixed(2)}</p>
                    <p>STT: ₹{charges.stt.toFixed(2)}</p>
                    <p>Total Charges: ₹{charges.total_charges.toFixed(2)}</p>
                    <p><strong>Net Value: ₹{charges.net_value.toFixed(2)}</strong></p>
                </div>
            )}
        </div>
    );
}

export default ChargeCalculator;
```

### Cost Notifications Widget
```jsx
import { useEffect, useState } from 'react';

function CostNotifications() {
    const [notifications, setNotifications] = useState([]);

    useEffect(() => {
        fetch('/api/notifications/cost-updates?limit=5', {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        })
            .then(r => r.json())
            .then(data => setNotifications(data.notifications));
    }, []);

    const markAsRead = async (id) => {
        await fetch(`/api/notifications/${id}/read`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        setNotifications(n => n.filter(x => x.id !== id));
    };

    return (
        <div>
            <h3>Cost Update Notifications</h3>
            {notifications.map(notif => (
                <div key={notif.id}>
                    <p>{notif.message}</p>
                    <small>{new Date(notif.created_at).toLocaleString()}</small>
                    <button onClick={() => markAsRead(notif.id)}>Dismiss</button>
                </div>
            ))}
        </div>
    );
}

export default CostNotifications;
```

## Error Handling

All endpoints return errors with consistent format:
```json
{
    "error": "Description of what went wrong",
    "status": "error_code"
}
```

Common status codes:
- `200 OK`: Success
- `400 Bad Request`: Missing/invalid parameters
- `403 Forbidden`: Insufficient permissions (not admin)
- `404 Not Found`: Resource doesn't exist
- `500 Internal Server Error`: Unexpected error

## Rate Limiting (Optional)

Add rate limiting to prevent abuse:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route('/api/costs/calculate', methods=['POST'])
@limiter.limit("10 per minute")  # 10 calculations per minute per user
@require_auth
def api_calculate_trade_charges():
    ...
```

## Logging

All API calls are logged with:
- User email
- Timestamp
- Endpoint
- Parameters
- Response status

Check logs via:
```bash
tail -f /var/log/grow_trading_bot/app.log | grep "cost"
```

## Testing via cURL

```bash
# Health check
curl -H "Authorization: Bearer <token>" \
  http://localhost:5000/api/costs/health

# Get config
curl -H "Authorization: Bearer <token>" \
  http://localhost:5000/api/costs/config

# Calculate charges
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"side":"BUY","quantity":10,"price":2500}' \
  http://localhost:5000/api/costs/calculate

# Get history
curl -H "Authorization: Bearer <token>" \
  'http://localhost:5000/api/costs/history?cost_type=brokerage_flat_per_order&days=30'

# Manual check (admin)
curl -X POST \
  -H "Authorization: Bearer <admin_token>" \
  http://localhost:5000/api/costs/manual-check

# Notifications
curl -H "Authorization: Bearer <token>" \
  'http://localhost:5000/api/notifications/cost-updates?limit=5'
```
