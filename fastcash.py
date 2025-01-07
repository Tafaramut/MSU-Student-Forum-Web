import json
import uuid
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from twilio.rest import Client
from redis_connection import redis_client
import requests


load_dotenv()

API_URL = "http://13.244.174.167:30891/api/v1/fastcash/start"
HEADERS = {"Content-Type": "application/json"}
USSD_URL = "https://f1ef-197-221-255-251.ngrok-free.app/ussd"

session_state = {}
user_data = redis_client.get("some_key")
account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')


twilio_client = Client(account_sid, auth_token)


CURRENCY_MENU = "*Select currency to be debited:*\n1. USD\n2. ZWG\n3. ZAR\n4. EURO"

def format_confirmation_message(camunda_data):
    """Format the confirmation message to display key-value pairs."""
    message_lines = [
        f"\n*Currency:* \t\t\t\t{camunda_data['currency']}",
        f"*Beneficiary Name:* \t\t{camunda_data['beneficiaryName']}",
        f"*Surname:* \t\t\t\t{camunda_data['surname']}",
        f"*Phone Number:* \t\t{camunda_data['phoneNumber']}",
        f"*Amount:* \t\t\t\t{camunda_data['amount']}",
        f"*Reference Number:* \t{camunda_data['referenceNumber']}",
        f"*Expiry Date:* \t\t\t{camunda_data['expiryDate']}\n"
    ]
    return "\n".join(message_lines)

def notify_beneficiary(camunda_data, sender_name):
    """Send notification to the beneficiary."""
    message_lines = [
        f"Hello {camunda_data['beneficiaryName']},",
        f"You have received money from {sender_name}. Please collect it before it expires.",
        f"\n*Currency:* {camunda_data['currency']}",
        f"*Amount:* {camunda_data['amount']}",
        f"*Reference Number:* {camunda_data['referenceNumber']}",
        f"*Expiry Date:* {camunda_data['expiryDate']}\n"
    ]
    beneficiary_message = "\n".join(message_lines)

    try:
        # Send message to the beneficiary
        twilio_client.messages.create(
            from_=f"{twilio_phone_number}",
            to=f"whatsapp:{camunda_data['phoneNumber']}",
            body=beneficiary_message
        )
        print(f"Notification sent to beneficiary at {camunda_data['phoneNumber']}.")
    except Exception as e:
        print(f"Failed to send notification to beneficiary: {e}")


# Function to trigger USSD
def trigger_ussd(session_id, phone_number):
    try:
        ussd_response = requests.post(USSD_URL, data={
            'sessionId': session_id,
            'phoneNumber': phone_number,
            'text': ''
        })
        if ussd_response.status_code == 200:
            twilio_client.messages.create(
                from_=twilio_phone_number,
                to=phone_number,
                body=f"USSD Session Started:\n\n{ussd_response.text.strip()}"
            )
            return "USSD triggered and response sent via SMS."
        else:
            return f"Failed to trigger USSD. Error: {ussd_response.text}"
    except Exception as e:
        print(f"Error triggering USSD: {e}")
        return "Error occurred while triggering USSD."


# Functions for handling specific flows
def handle_self_voucher(sender_phone, message, response):
    if sender_phone not in session_state:
        session_state[sender_phone] = {"default_state": "initialized"}

        # Access state safely
    state = session_state[sender_phone]
    """Handle 'send voucher to self' flow."""
    user_data = json.loads(redis_client.get(sender_phone))


    if 'currency' not in state['camunda_data']:
        currency_map = {'1': 'USD', '2': 'ZWG', '3': 'ZAR', '4': 'EURO'}
        if message in currency_map:
            state['camunda_data']['currency'] = currency_map[message]
            response.message("Enter amount you want to withdraw:")
        else:
            response.message("Invalid choice. " + CURRENCY_MENU)
    elif 'amount' not in state['camunda_data']:
        if message.isdigit():
            state['camunda_data']['amount'] = float(message)
            response.message("Write the account number you want to debit from:")
        else:
            response.message("Please enter a valid amount:")
    elif 'account' not in state['camunda_data']:
        state['camunda_data']['account'] = message
        camunda_data = prepare_camunda_data(user_data, state['camunda_data'], sender_phone)
        session_state[sender_phone]['camunda_data'] = camunda_data
        formatted_message = format_confirmation_message(camunda_data)
        response.message(f"*Review your details:*\n{formatted_message}\nSend *CONFIRM* to proceed or *CANCEL* to abort.")
        state['state'] = 'confirm_self'


def handle_send_voucher(sender_phone, message, response):
    """Handle 'send voucher to someone' flow."""
    state = session_state[sender_phone]
    user_data = json.loads(redis_client.get(sender_phone))

    if 'account' not in state['camunda_data']:
        state['camunda_data']['account'] = message
        response.message("Write the beneficiary's name and surname:")
    elif 'beneficiaryName' not in state['camunda_data']:
        # Split the full name into first and last names
        full_name = message.split()
        if len(full_name) < 2:
            response.message("Please provide both the beneficiary's first and last names:")
            return  # Wait for valid input
        state['camunda_data']['beneficiaryName'] = " ".join(full_name[:-1])  # All but last word
        state['camunda_data']['surname'] = full_name[-1]  # Last word
        response.message("Write the beneficiary's phone number:")
    elif 'phoneNumber' not in state['camunda_data']:
        # Validate phone number (basic length check)
        if not message.isdigit() or len(message) < 8:
            response.message("Please provide a valid phone number:")
            return  # Wait for valid input

        # Remove the first digit and replace it with +263
        formatted_phone_number = "+263" + message[1:]

        # Store the formatted phone number
        state['camunda_data']['phoneNumber'] = formatted_phone_number
        response.message(CURRENCY_MENU)
    elif 'currency' not in state['camunda_data']:
        currency_map = {'1': 'USD', '2': 'ZWG', '3': 'ZAR', '4': 'EURO'}
        if message in currency_map:
            state['camunda_data']['currency'] = currency_map[message]
            response.message("Enter amount you want to send:")
        else:
            response.message("Invalid choice. " + CURRENCY_MENU)
    elif 'amount' not in state['camunda_data']:
        # Validate amount
        try:
            amount = float(message)
            if amount <= 0:
                raise ValueError("Amount must be greater than zero.")
            state['camunda_data']['amount'] = amount
            camunda_data = prepare_camunda_data(user_data, state['camunda_data'], sender_phone)
            session_state[sender_phone]['camunda_data'] = camunda_data
            formatted_message = format_confirmation_message(camunda_data)
            response.message(f"Review your details:\n{formatted_message}\nSend *CONFIRM* to proceed or *CANCEL* to abort.")
            state['state'] = 'confirm_send'
        except ValueError:
            response.message("Please enter a valid amount greater than zero:")


def prepare_camunda_data(user_data, camunda_data, sender_phone):
    """Prepare the Camunda data object."""
    full_name = user_data['full_name'].split()
    first_name = " ".join(full_name[:-1])
    surname = full_name[-1]
    return {
        "taskId": "",
        "processInstanceId": "",
        "processDefinitionKey": "",
        "email": user_data['email'],
        "account": camunda_data['account'],
        "currency": camunda_data['currency'],
        "beneficiaryName": camunda_data.get("beneficiaryName", first_name),
        "surname": camunda_data.get("surname", surname),
        "phoneNumber": camunda_data.get("phoneNumber", sender_phone),
        "amount": camunda_data['amount'],
        "idNumber": user_data['id_number'],
        "referenceNumber": str(uuid.uuid4()).replace("-", "")[:16],
        "pin": str(random.randint(100000, 999999)),
        "expiryDate": (datetime.now() + timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S"),
        "completionStatus": "pending",
        "isExpired": False
    }


