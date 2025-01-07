from flask import Flask, request

app = Flask(__name__)

# Simulated database for session tracking
sessions = {}

@app.route('/ussd', methods=['POST'])
def ussd():
    # Extract parameters from the incoming request
    session_id = request.form.get('sessionId')
    phone_number = request.form.get('phoneNumber')
    text = request.form.get('text', '')

    # Initialize session if not already present
    if session_id not in sessions:
        sessions[session_id] = {'phone_number': phone_number, 'state': 0}

    # Determine the response based on the session state
    state = sessions[session_id]['state']
    if state == 0:
        response_text = "Welcome! Press 1 for balance, 2 for exit."
        sessions[session_id]['state'] = 1
    elif state == 1:
        if text == '1':
            response_text = "Your balance is $100."
            sessions[session_id]['state'] = 0  # Reset state
        elif text == '2':
            response_text = "Goodbye!"
            sessions[session_id]['state'] = 0  # Reset state
        else:
            response_text = "Invalid option. Please press 1 or 2."
    else:
        response_text = "Session expired. Please restart."

    # Respond in USSD format
    return f" {response_text}"

@app.route('/trigger_ussd', methods=['POST'])
def trigger_ussd():
    """Endpoint to trigger USSD from another function."""
    session_id = request.json.get('sessionId', 'default_session')
    phone_number = request.json.get('phoneNumber', '+1234567890')

    # Simulate an incoming USSD request
    return ussd()  # Call the USSD function directly

if __name__ == '__main__':
    app.run(port=5001)  # Run on port 5001