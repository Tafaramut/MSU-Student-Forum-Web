import os
from flask import send_file, abort
from twilio.twiml.messaging_response import MessagingResponse
import logging

logging.basicConfig(level=logging.DEBUG)

# Dictionary to map insurance products to their corresponding PDFs
insurance_pdfs = {
    "1": "gold_insurance.pdf",
    "2": "chrome_insurance.pdf",
    "3": "diamond_insurance.pdf",
    "4": "platinum_insurance.pdf",
    "5": "ruby_insurance.pdf",
}

# Path to your PDF storage
PDF_STORAGE_PATH = "media_files"


def handle_vehicle_insurance(user_number, incoming_msg, user_sessions):
    if user_number not in user_sessions:
        user_sessions[user_number] = {"step": None}
        logging.debug(f"Initialized new session for {user_number}")

    # Update the user's session step
    user_sessions[user_number]["step"] = "vehicle_insurance_forms"
    logging.debug(f"User {user_number} step updated to 'vehicle_insurance'")

    """
    Handles the 'vehicle_insurance' user step.
    """
    response = MessagingResponse()

    if incoming_msg in insurance_pdfs:
        pdf_filename = insurance_pdfs[incoming_msg]
        pdf_path = os.path.join(PDF_STORAGE_PATH, pdf_filename)

        if os.path.exists(pdf_path):
            response_msg = (
                f"Great choice! You selected {pdf_filename.replace('_', ' ').title()} insurance."
                "\n\nPlease fill out the attached form and submit it back via WhatsApp."
                "\n\nType *BACK* to return to the main menu."
            )
            # Replace with your ngrok public URL
            file_url = f"https://7e85-77-246-55-169.ngrok-free.app/pdf/{pdf_filename}"
            message = response.message(response_msg)
            message.media(file_url)

            user_sessions[user_number]["step"] = "vehicle_insurance"

        else:
            response.message(
                "The selected PDF form is not available at the moment. Please try again later."
            )

    elif incoming_msg.lower() == "back":
        # Returning to the main insurance menu
        message = response.message(
            "Returning to the insurance menu. Please select an option:\n"
            "1. Gold Insurance\n"
            "2. Chrome Insurance\n"
            "3. Diamond Insurance\n"
            "4. Platinum Insurance\n"
            "5. Ruby Insurance"
        )
        user_sessions[user_number]["step"] = "vehicle_insurance"

    else:
        response.message(
            "Invalid option. Please select a valid insurance type by typing the corresponding number."
        )

    return str(response)  # Return the Twilio response object as string
