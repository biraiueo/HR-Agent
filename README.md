# TensorFlowAI
TalentFlow AI Agent is an automated assistant designed to accelerate the recruitment process. This project uses Google API integration and AI models to automate manual tasks, from detecting new job applications to scheduling interviews and storing candidate data.

<img width="940" height="515" alt="image" src="https://github.com/user-attachments/assets/eb9eaf9c-6460-48ef-a583-493d9536f46b" />

Key Features
•	Automatic Email Processing: Automatically scans Gmail inboxes to detect new job application emails.
•	Smart Resume Extraction: Accurately extracts text only from PDF resume attachments, ignoring text in the email body.
•	AI-Powered Screening: Uses Google's advanced AI models (Gemini 1.5 Flash) to analyze and assess resume fit against predefined job descriptions.
•	Automated Scheduling: Automatically schedules interviews in Google Calendar for candidates who pass the screening and sends email invitations.
•	Automatic Data Recording: Save processed candidate data, including AI-generated resume summaries, to Google Sheets.

Program Workflow
This program is designed to run continuously. When executed, it will perform the following steps:
1.	Detect Applications: Using the Google Gmail API, the program searches for new emails with the subject "Job Application" that have not been read.
2.	Extracting Information: For each email, it downloads and extracts text from PDF attachments, then identifies the candidate's name and email address.
3.	Conducting Screening: The extracted resume text is analyzed by an AI model to determine its level of suitability (VERY SUITABLE, SUITABLE, or LESS SUITABLE).
4.	Determining Action:
o	Candidate Passes: If the candidate is VERY SUITABLE or SUITABLE, the program will search for available slots in Google Calendar, schedule an interview, and send an invitation email.
o	Candidate Rejected: If the candidate is LESS SUITABLE, the program will send an automatic rejection email.
5.	Recording: Candidate data, interview schedules, and resume summaries will be automatically recorded in Google Sheets.

Installation and Configuration
1.	Credential Preparation
    •	Google API Key: GOOGLE_API_KEY is stored in the .env file. You must replace the value your_google_api_key_here with your actual API key.
    •	Google OAuth 2.0: The credentials.json file is the credentials you downloaded from the Google Cloud Console. You do not need to change its contents; just ensure the filename remains        credentials.json and it is located in the project's main folder.
    •	Google Sheets ID: Open the file hr_agent_real.py. Find the variable that holds the Google Sheets ID. It will typically look like this: SPREADSHEET_ID = "YOUR_SPREADSHEET_ID". You           must replace YOUR_SPREADSHEET_ID with the unique ID of your Google Sheet.
    •	token.json: The file  is a credential file that will appear automatically when you first run the program. This file acts as a valid "key," enabling the program to interact with             Google APIs (such as Gmail, Calendar, and Sheets) without requiring re-authorization through the browser. Since this file contains sensitive information, it is crucial not to upload        it to GitHub or share it. If re-authorization is needed, simply delete this file, and the program will request it again automatically.

  	 IMPORTANT: When you first run the program and are prompted for API authorization, make sure you grant the necessary access permissions so that all TalentFlow AI Agent features can          function properly.
2.	Dependency Installation
    Ensure you have Python 3.7+ installed. Then, install all required libraries:
                                                                                pip install -r requirements.txt
    If you do not have a requirements.txt file, create one and add the following libraries:
    •	google-api-python-client g
    •	google-auth-oauthlib
    •	langchain
    •	langchain-google-genai
    •	PyMuPDF
    •	Flask python-dotenv python-dateutil

3.	How to Run
    After all configurations are complete, run the program through the terminal:
                                                                                            python api.py
    Open your web browser and visit http://127.0.0.1:5000 to view the dashboard
    and operate the agent.
