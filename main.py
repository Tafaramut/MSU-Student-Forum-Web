import os
import json
import uuid
import re
from twilio.rest import Client
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
import requests
import spacy
from redis_connection import redis_client
import tempfile
from flask import Flask, request, send_from_directory
from requests.auth import HTTPBasicAuth
from fastcash import format_confirmation_message, notify_beneficiary, handle_self_voucher, handle_send_voucher, trigger_ussd, CURRENCY_MENU
from redspere import  load_spreadsheet, prepare_loan_application
from email_document_upload import send_email_with_attachment

user_data = redis_client.get("some_key")

# Load SpaCy model
nlp = spacy.load("en_core_web_sm")

load_dotenv()
app = Flask(__name__)

API_URL = "http://13.244.174.167:30891/api/v1/fastcash/start"
HEADERS = {"Content-Type": "application/json"}
USSD_URL = "https://f1ef-197-221-255-251.ngrok-free.app/ussd"

# user_data = redis_client.get("some_key")
account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')

MAIN_MENU = "*Choose an option:*\n1. View all Services \n2. Make a Complaint\n3. General Queries\n4. Upload Documents"
FASTCASH_MENU = "*Welcome to FastCash...!*\n*Choose an option:*\n1. Send voucher to self\n2. Send voucher to someone"
ALL_SERVICES_MENU = "*Which product or service do you want to look into:*\n1. Banking \n2. RED-SPHERE Loans \n3. Insurance\n4. Fast Cash"
BANKING_PRODUCTS_MENU = ("* Here are the banking products we offer:*"
                         "\n1. Transactional Account\n2. Personal Banking \n3. Private Banking\n4. Wholesale Banking"
                         "\n5. Family Banking\n6. International Banking\n7. Wealth Banking\n8. Foreign National Banking")
INSURANCE_PRODUCTS_MENU = ("*Here are the insurance products we offer:*"
                           "\n1. Health Insurance\n2. Life Insurance (Funeral Plan\n3. Vehicle Insurance"
                           "\n4. Home/Property Insurance\n5. Personal All Risks Insurance")
RED_SPHERE_LOANS = ("*Login successful! Here are the Loan products we offer at RedSphere:*"
                           "\n1. Available Loans \n2. My Loans \n3. My Details \n4. Credit Score")
LOAN_CATEGORY = ("'*Please choose an option:*\n\n1. Salary Based Loans\n2. Pensions Loan\n3. Pay Day Loan\n"
                "4. School Loan\n5. Order Financing\n")
SUBJECT_MENU = ("Which document file do you want to upload to our mailbox.\n*Please choose an option:*\n1. Loan Application Form\n2. Proof of Residence\n3. Pay Slip")

session_state = {}
twilio_client = Client(account_sid, auth_token)

# Function to process incoming messages with SpaCy
def process_message_with_spacy(message):
    doc = nlp(message)
    if "home" in [token.text.lower() for token in doc]:
        return "HOME"
    elif "back" in [token.text.lower() for token in doc]:
        return "BACK"
    return None


@app.route('/whatsapp', methods=['POST'])
def whatsapp_bot():
    sender_phone = request.form.get('From').replace("whatsapp:", "")
    sender_name = request.form.get("ProfileName")
    message = request.form.get('Body', '').strip().lower()
    media_url = request.form.get('MediaUrl0')  # URL of the file
    media_type = request.form.get('MediaContentType0')  # MIME type of the file
    media_filename = request.form.get('MediaFilename0')  # Filename of the file

    response = MessagingResponse()

    user_data = redis_client.get(sender_phone)

    if sender_phone not in session_state:
        session_state[sender_phone] = {'state': 'start', 'history': []}

    state = session_state[sender_phone]['state']
    history = session_state[sender_phone].get('history', [])


        # Handle confirmation directly in /whatsapp
    if state == 'confirm_self' or state == 'confirm_send':
        if message == "confirm":
            camunda_data = session_state[sender_phone]['camunda_data']

            # Debug: Log the data being sent
            print("Sending the following data to Camunda:")
            print(json.dumps(camunda_data, indent=2))

            # Make the API call
            try:
                api_response = requests.post(API_URL, json=camunda_data, headers=HEADERS)

                # Debug: Log the API response
                print(f"Status Code: {api_response.status_code}")
                print(f"Response Text: {api_response.text}")

                if api_response.status_code == 200:
                    if state == 'confirm_send':
                        # Notify the beneficiary
                        sender_name = user_data and json.loads(user_data).get('full_name', 'Unknown Sender')
                        notify_beneficiary(camunda_data, sender_name)
                        # Trigger USSD flow
                        ussd_response = trigger_ussd(session_id=str(uuid.uuid4()), phone_number=sender_phone)
                        print(f"USSD Response: {ussd_response}")

                    del session_state[sender_phone]
                    response.message("Voucher processed successfully!")
                else:
                    response.message(f"Failed to process voucher. Error: {api_response.text}")
            except requests.exceptions.RequestException as e:
                print(f"Error during API call: {e}")
                response.message("An error occurred while processing your request. Please try again later.")
        elif message == "cancel":
            del session_state[sender_phone]
            response.message("Process cancelled.")
        else:
            # Use the formatting function to display the confirmation message
            camunda_data = session_state[sender_phone]['camunda_data']
            formatted_message = format_confirmation_message(camunda_data)
            response.message(
                f"Review your details:\n{formatted_message}\nSend *CONFIRM* to proceed or *CANCEL* to abort.")
        return str(response)

    # Handle special commands (BACK, HOME)
    special_command = process_message_with_spacy(message)
    if special_command == "HOME":
        session_state[sender_phone]['state'] = 'menu'
        response.message(MAIN_MENU)
        return str(response)

    if special_command == "BACK":
        if history:
            # Pop the last state and revert to it
            previous_state = history.pop()
            session_state[sender_phone]['state'] = previous_state
            session_state[sender_phone]['history'] = history

            # Send the corresponding menu or message for the previous state
            if previous_state == 'menu':
                response.message(MAIN_MENU)
            elif previous_state == 'self_voucher':
                response.message(CURRENCY_MENU)
            elif previous_state == 'send_voucher':
                response.message("Write the account number you want to debit from:")
            elif previous_state == 'loans':
                response.message(LOAN_CATEGORY)
            elif previous_state == 'loan category':
                response.message(
                    "Welcome to Red-Sphere Loans! Please choose an option:\n\n"
                    "1. Salary Based Loans\n"
                    "2. Pensions Loan\n"
                    "3. Pay Day Loan\n"
                    "4. School Loan\n"
                    "5. Order Financing\n"
                )
            elif previous_state == 'selecting_loan':
                response.message(
                    f"Please enter the amount you want to borrow.")
            elif previous_state == 'awaiting_amount':
                if message.isdigit():
                    session_state[sender_phone]['amount'] = message
                    session_state[sender_phone]['state'] = 'awaiting_tenure'
                    response.message(
                        "Thank you! Please select the tenure for your loan:\n"
                        "1. 6 months\n"
                        "2. 12 months\n"
                        "3. 24 months\n"
                    )
                else:
                    response.message("Please enter a valid amount.")
            elif previous_state == 'awaiting_tenure':
                tenures = {'1': '6 months', '2': '12 months', '3': '24 months'}
                selected_tenure = tenures.get(message)

                if selected_tenure:
                    session_state[sender_phone]['tenure'] = selected_tenure

                    loan_product = session_state[sender_phone].get('loan_product')
                    amount = session_state[sender_phone].get('amount')

                    response.message(
                        f"Here is your application summary:\n\n"
                        f"Loan Product: {loan_product}\n"
                        f"Amount: {amount}\n"
                        f"Tenure: {selected_tenure}\n\n"
                        "Reply 'CONFIRM' to submit your application, or 'CANCEL' to start over."
                    )
                    session_state[sender_phone]['state'] = 'confirming_application'
                else:
                    response.message("Invalid selection. Please choose a tenure: 1, 2, or 3.")

            elif previous_state == 'confirming_application':
                if message == 'confirm':
                    if sender_phone in session_state:
                        del session_state[sender_phone]
                        response.message(
                            "Thank you! Your loan application has been submitted.\n"
                            "Our team will review it and send you an approval message shortly."
                        )
                    else:
                        response.message("Session has expired or does not exist.")

                elif message == 'cancel':
                    del session_state[sender_phone]
                    response.message("Your application has been canceled. You can start over anytime.")
                else:
                    response.message("Please reply 'CONFIRM' to submit your application or 'CANCEL' to cancel.")
            else:
                response.message(f"Returning to {previous_state}.")
        else:
            # No history available
            response.message("No previous menu to return to.")
        return str(response)


    # State handling logic
    if state == 'start':
        if user_data:
            response.message(f"*Welcome, {sender_name}...!*\n*How can we help you today?*"
                            f"{MAIN_MENU}")
            session_state[sender_phone]['state'] = 'menu'
        else:
            session_state[sender_phone]['state'] = 'create_account'
            response.message(f"*Hi there, {sender_name}...! I am DANAI, your CBZ Self-Service Assistant.! Please create your account.*\n\nSend your full name:")
    elif state == 'create_account':
        if 'full_name' not in session_state[sender_phone]:
            session_state[sender_phone]['full_name'] = message.title()
            response.message("Enter your email:")
        elif 'email' not in session_state[sender_phone]:
            if  "@" in message and "." in message:
                session_state[sender_phone]['email'] = message
                response.message("Enter your ID number:")
            else:
                response.message("That doesn't look like a valid email. Please enter a valid *email address*.")

        # Inside your condition:
        elif 'id_number' not in session_state[sender_phone]:
            # Updated pattern to enforce exactly five digits in the middle
            pattern = r"^\d{2}-\d{5,}[a-z]\d{2}$"
            print(f"Received ID: {message}")  # Debugging: Print the received message
            if re.match(pattern, message):
                session_state[sender_phone]['id_number'] = message
                redis_client.set(sender_phone, json.dumps({
                    "full_name": session_state[sender_phone]['full_name'],
                    "email": session_state[sender_phone]['email'],
                    "id_number": session_state[sender_phone]['id_number']
                }))
                session_state[sender_phone]['state'] = 'menu'
                response.message(f"*Your account was created successfully!*\n\n{MAIN_MENU}")
            else:
                print("No match. Invalid ID format.")  # Debugging: Explain why it failed
                response.message("National ID must follow the format 63-11167B63. Please try again.")

    elif state == 'menu':
        if message == '1':
            response.message(ALL_SERVICES_MENU)
            session_state[sender_phone]['state'] = 'view_all_services'
        elif message == '2':
            session_state[sender_phone]['state'] = 'make_complaint'
            # session_state[sender_phone]['camunda_data'] = {}
            response.message("Make a Complaint:")
        elif message == '3':
            session_state[sender_phone]['state'] = 'general_queries'
            # session_state[sender_phone]['camunda_data'] = {}
            response.message("General Queries:")
        elif message == '4':
            response.message(SUBJECT_MENU)
            session_state[sender_phone]['state'] = 'upload_documents'

        else:
            response.message("Invalid option. Please try again.\n" + MAIN_MENU)

    elif state == 'view_all_services':
        if user_data and  message == '1':
            response.message(BANKING_PRODUCTS_MENU)
            session_state[sender_phone]['state'] = 'banking'
        elif user_data and message == '2':
            response.message(RED_SPHERE_LOANS)
            session_state[sender_phone]['state'] = 'loans'
        elif message == '3':
            response.message(INSURANCE_PRODUCTS_MENU)
            session_state[sender_phone]['state'] = 'insuarance'
        elif user_data and message == '4':
            response.message(FASTCASH_MENU)
            session_state[sender_phone]['state'] = 'fastcash'
        else:
            response.message("Invalid option. Please try again.\n" + ALL_SERVICES_MENU)

    elif state == 'make_complaint':
        response.message('Type in the message of yor complaint and I will send it to responsible personale.')
        session_state[sender_phone]['state'] = 'sender_complaint'
    elif state == 'general_queries':
        handle_send_voucher(sender_phone, message, response)

    elif state == 'fastcash':
        if message == '1':
            session_state[sender_phone]['state'] = 'self_voucher'
            session_state[sender_phone]['camunda_data'] = {}
            response.message(CURRENCY_MENU)

        elif message == '2':
            session_state[sender_phone]['state'] = 'send_voucher'
            session_state[sender_phone]['camunda_data'] = {}
            response.message("Write the account number you want to debit from:")
        else:
            response.message("Invalid option. Please try again.\n" + FASTCASH_MENU)
    elif state == 'self_voucher':
        handle_self_voucher(sender_phone, message, response)
    elif state == 'send_voucher':
        handle_send_voucher(sender_phone, message, response)

    elif state == 'upload_documents':
        if message.isdigit():
            options = {
                '1': 'Loan Application Form',
                '2': 'Proof of Residence',
                '3': 'Pay Slip'
            }
            session_state[sender_phone]['subject'] = options[message]
            session_state[sender_phone]['state'] = 'awaiting_file'
            response.message(f"*Please submit the '{session_state[sender_phone]['subject']}'file.*")
        else:
            response.message("Invalid choice. Please choose:\n1. Loan Application Form\n2. Proof of Residence\n3. Pay Slip")


    elif state == 'awaiting_file':
        session_state[sender_phone]['caption'] = message

        if media_type in ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            response.message(f"File '{media_filename}' received. Processing your document...")
            # Download the document
            account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            file_content = requests.get(media_url, auth=HTTPBasicAuth(account_sid, auth_token)).content
            if not file_content:
                response.message("Failed to download the document. Please try again.")
                return str(response)
            # Save the file temporarily
            file_suffix = '.pdf' if media_type == 'application/pdf' else '.docx'
            with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as temp_file:
                temp_file.write(file_content)
                temp_file_path = temp_file.name
            try:
                # Send the document as an email attachment
                send_email_with_attachment(
                    file_path=temp_file_path,
                    subject=f"REF: {session_state[sender_phone]['subject']}",
                    filename=media_filename,
                    caption=f"Caption: {session_state[sender_phone]['caption']}"
                )
                response.message(
                    f"Your '{session_state[sender_phone]['subject']}' has been processed and emailed successfully.")
            except Exception as e:
                response.message(f"Error processing the file: {str(e)}")
            finally:
                # Clean up temporary file
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            # Reset user state
            del session_state[sender_phone]
        else:
            response.message("Please send a valid PDF or Word document.")
        return str(response)

    elif state == 'loans':
        if message == '1':
            response.message(LOAN_CATEGORY)
            session_state[sender_phone]['state'] = 'loan_category'
        elif message == '2':  # User selects "My Loans"
            user_email = session_state[sender_phone].get('email')
            if not user_email:
                response.message("We couldn't find your email. Please try logging in again.")
            else:
                # Fetch loans using the provided email
                api_url = "http://13.244.174.167:30875/api/v1/loans/retrieve-loan-application-by-email"
                headers = {"Content-Type": "application/json"}
                try:
                    api_response = requests.get(api_url, params={"email": user_email}, headers=headers)
                    if api_response.status_code == 200:
                        loans = api_response.json()  # Assuming the API returns a JSON response
                        if loans:
                            # Construct a response message listing the user's loans
                            loan_list = "*Here are your loan applications:*\n"
                            for idx, loan in enumerate(loans, start=1):
                                loan_details = (
                                    f"{idx}. Loan ID: {loan.get('customId', 'N/A')}\n"
                                    f"   Amount: {loan.get('loanAmount', 'N/A')}\n"
                                    f"   Status: {loan.get('approvalStatus', 'N/A')}\n"
                                    f"   Payment Date: {loan.get('loanPaymentDate', 'N/A')}\n\n"
                                )
                                loan_list += loan_details
                            response.message(loan_list)
                        else:
                            response.message("You currently have no loan applications.")
                    else:
                        response.message("We encountered an issue retrieving your loans. Please try again later.")
                except Exception as e:
                    print("Error fetching loans:", str(e))
                    response.message("There was an error retrieving your loan applications. Please try again later.")
        elif message == '3':
            response.message("My Details feature is coming soon!")
        elif message == '4':
            response.message("Credit Score feature is coming soon!")
        else:
            response.message(
                "Please choose a valid option:\n1. Available Loans\n2. My Loans\n3. My Details\n4. Credit Score")


    elif state =='loan_category':
        if message.isdigit():
            loan_category = message
            # Filter loans based on category and cache results
            data = load_spreadsheet()
            options_map = {
                '1': 'Salary Based Loans',
                '2': 'Pensions Loan',
                '3': 'Pay Day Loan',
                '4': 'School Loan',
                '5': 'Order Financing',
            }
            selected_keyword = options_map.get(loan_category, None)
            if selected_keyword:
                key_words = " ".join(selected_keyword.split()[:1])
                matching_rows = data[data['Product Name'].str.contains(key_words, case=False, na=False)]

                if not matching_rows.empty:
                    matching_loans = matching_rows.to_dict('records')  # Convert matching rows to list of dictionaries
                    session_state[sender_phone]['loan_category'] = loan_category
                    session_state[sender_phone]['state'] = 'selecting_loan'
                    session_state[sender_phone]['matching_loans'] = matching_loans  # Store filtered loans as a list

                    response_message = "Here are the available loans:\n\n"
                    for idx, loan in enumerate(matching_loans, start=1):
                        response_message += f"*{idx}. {loan['Product Name']}*\n"
                        response_message += "\n".join([f"{key}: {value}" for key, value in loan.items()])
                        response_message += "\n\n\n"
                    response_message += "\nReply with the number of the loan you want to choose."
                    response.message(response_message)  # Use response.message()
                else:
                    response.message("No matching loans found. Please start again.")
            else:
                response.message("Invalid category selection. Please choose a valid category number.")
        else:
            response.message(
                "Welcome to Red-Sphere Loans! Please choose an option:\n\n"
                "1. Salary Based Loans\n"
                "2. Pensions Loan\n"
                "3. Pay Day Loan\n"
                "4. School Loan\n"
                "5. Order Financing\n"
            )
    elif state == 'selecting_loan':
        if message.isdigit():
            loan_number = int(message)

            # Retrieve the filtered loans from session_state
            matching_loans = session_state[sender_phone].get('matching_loans')
            if not matching_loans:
                response.message("No matching loans found. Please start again.")
            else:
                if 1 <= loan_number <= len(matching_loans):
                    selected_loan = matching_loans[loan_number - 1]['Product Name']
                    session_state[sender_phone]['loan_product'] = selected_loan
                    session_state[sender_phone]['state'] = 'awaiting_amount'

                    response.message(
                        f"You have selected '{selected_loan}'. Please enter the amount you want to borrow.")
                else:
                    response.message("Invalid loan number. Please select a valid loan number from the list.")
        else:
            response.message("Invalid input. Please reply with the loan number you want to choose.")

    elif state =='awaiting_amount':
        if message.isdigit():
            session_state[sender_phone]['amount']= message
            session_state[sender_phone]['state'] = 'awaiting_tenure'
            response.message(
                "Thank you! Please select the tenure for your loan:\n"
                "1. 6 months\n"
                "2. 12 months\n"
                "3. 24 months\n"
            )
        else:
            response.message("Please enter a valid amount.")

    elif state == 'awaiting_tenure':
        tenures = {'1': '6 months', '2': '12 months', '3': '24 months'}
        selected_tenure = tenures.get(message)

        if selected_tenure:
            session_state[sender_phone]['tenure'] = selected_tenure

            loan_product = session_state[sender_phone].get('loan_product')
            amount = session_state[sender_phone].get('amount')

            response.message(
                f"Here is your application summary:\n\n"
                f"Loan Product: {loan_product}\n"
                f"Amount: {amount}\n"
                f"Tenure: {selected_tenure}\n\n"
                "Reply 'CONFIRM' to submit your application, or 'CANCEL' to start over."
            )
            session_state[sender_phone]['state'] = 'confirming_application'
        else:
            response.message("Invalid selection. Please choose a tenure: 1, 2, or 3.")


    elif state == 'confirming_application':
        if message.lower() == 'confirm':
            # Prepare data for the application
            user_data = {
                "email": session_state[sender_phone]['email'],
                "id_number": session_state[sender_phone]['id_number']
            }
            camunda_data = {
                "tenure": session_state[sender_phone]['tenure'],
                "amount": session_state[sender_phone]['amount'],
                "loan_product": session_state[sender_phone]['loan_product']
            }
            loan_application = prepare_loan_application(user_data, camunda_data)
            # Print the populated loan application object to the console
            print("Loan Application Data:", loan_application)
            # Send the loan application to the API
            api_url = "http://13.244.174.167:30875/api/v1/loans/apply-loan"
            headers = {"Content-Type": "application/json"}
            try:
                response_api = requests.post(api_url, json=loan_application, headers=headers)
                if response_api.status_code == 200:
                    print("API Response:", response_api.json())  # Print the API response to the console
                    del session_state[sender_phone]  # Clear session after successful submission
                    response.message(
                        f"Thank you! Your loan application with ID {loan_application['customId']} has been submitted.\n"
                        "Our team will review it and send you an approval message shortly."
                    )
                else:
                    print("API Error:", response_api.status_code, response_api.text)  # Log the error details
                    response.message("There was an issue submitting your loan application. Please try again later.")
            except Exception as e:
                print("API Request Failed:", str(e))  # Log the exception details
                response.message("There was an error processing your loan application. Please try again later.")
        elif message.lower() == 'cancel':
            del session_state[sender_phone]
            response.message("Your application has been canceled. You can start over anytime.")
        else:
            response.message("Please reply 'CONFIRM' to submit your application or 'CANCEL' to cancel.")

    else:
        response.message("Invalid responce. You need to start over")

    # Ensure sender_phone exists in session_state
    if sender_phone not in session_state:
        session_state[sender_phone] = {
            'history': [],  # Initialize history
            'state': None  # Initialize state or any other defaults you need
        }

    # Now it's safe to add the current state to history
    history = session_state[sender_phone]['history']
    history.append(state)  # Add the current state to history
    session_state[sender_phone]['history'] = history  # Update the session state

    return str(response)

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    """Serve files for download."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)
