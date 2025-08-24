import os
import datetime
import base64
import fitz 
import io
import json
import re
from email.mime.text import MIMEText
from dateutil import parser 

from dotenv import load_dotenv

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import InstalledAppFlow

from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.prompts import PromptTemplate


SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar.events', 
    'https://www.googleapis.com/auth/spreadsheets',   
    'https://www.googleapis.com/auth/gmail.modify'    
]

def get_google_services():
    """
    Mengatur otentikasi untuk Google API. 
    Akan meminta otorisasi browser jika token.json tidak ada atau tidak valid.
    """
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    return {
        'gmail': build('gmail', 'v1', credentials=creds),
        'calendar': build('calendar', 'v3', credentials=creds),
        'sheets': build('sheets', 'v4', credentials=creds)
    }

def _get_new_job_applications_logic() -> list[str]:
    """
    Logika inti untuk mengambil email lamaran pekerjaan baru dari Gmail.
    Email dianggap sebagai lamaran jika subjeknya 'Lamaran Pekerjaan'.
    Hanya mengambil email yang BELUM DIBACA.
    Mengembalikan daftar ID email yang ditemukan.
    """
    try:
        service = get_google_services()['gmail']
        results = service.users().messages().list(userId='me', q='subject:"Lamaran Pekerjaan" is:unread').execute()
        messages = results.get('messages', [])
        
        if not messages:
            return []
            
        email_ids = [msg['id'] for msg in messages]
        return email_ids
    except HttpError as err:
        print(f"Error mengambil email: {err.content.decode('utf-8')}")
        return []

def _mark_email_as_read_logic(email_id: str) -> str:
    """
    Menandai email dengan ID tertentu sebagai sudah dibaca (read).
    """
    try:
        service = get_google_services()['gmail']
        service.users().messages().batchModify(
            userId='me',
            body={
                'ids': [email_id],
                'removeLabelIds': ['UNREAD']
            }
        ).execute()
        return f"Email {email_id} berhasil ditandai sebagai sudah dibaca."
    except HttpError as err:
        error_msg = err.content.decode('utf-8')
        print(f"Gagal menandai email {email_id} sebagai dibaca: {error_msg}")
        return f"Gagal menandai email {email_id} sebagai dibaca: {error_msg}"
    except Exception as e:
        print(f"Error umum saat menandai email {email_id} sebagai dibaca: {e}")
        return f"Error umum saat menandai email {email_id} sebagai dibaca: {str(e)}"

def clean_extracted_name(name_text: str) -> str:
    """
    Membersihkan nama yang diekstrak dari teks.
    """
    if not name_text or name_text == "Tidak Diketahui":
        return "Tidak Diketahui"
    
    clean_name = re.sub(r'[^A-Za-z\s.,-]', '', name_text)
    
    clean_name = ' '.join(clean_name.split())
    
    name_parts = clean_name.split()
    if len(name_parts) > 3:
        clean_name = ' '.join(name_parts[:3])
    
    clean_name = clean_name.title()
    
    return clean_name

def clean_resume_text(resume_text: str) -> str:
    """
    Membersihkan teks resume dari karakter aneh dan format yang tidak rapi.
    """
    if not resume_text:
        return ""
    
    clean_text = re.sub(r'[^\w\s.,;:!?()\-+/@&%$#*]', ' ', resume_text)
    
    clean_text = re.sub(r'\s+', ' ', clean_text)
    
    clean_text = re.sub(r'\s+([.,;:!?)])', r'\1', clean_text)
    clean_text = re.sub(r'([(])\s+', r'\1', clean_text)
    
    sentences = re.split(r'([.!?])\s+', clean_text)
    clean_text = ''
    for i in range(0, len(sentences), 2):
        if i < len(sentences):
            sentence = sentences[i].strip()
            if sentence:
                sentence = sentence[0].upper() + sentence[1:] if sentence else ""
                clean_text += sentence
                if i + 1 < len(sentences):
                    clean_text += sentences[i + 1] + " "
    
    return clean_text.strip()

def _extract_applicant_info_from_email_id_logic(email_id: str) -> dict:
    """
    Logika inti untuk mengambil konten dari email, HANYA dari lampiran PDF jika ada, 
    dan mengekstrak info pelamar.
    """
    try:
        service = get_google_services()['gmail']
        msg = service.users().messages().get(userId='me', id=email_id, format='full').execute()
        
        resume_text = ""
        payload = msg['payload']
        
        print(f"Memproses payload email: {payload.get('mimeType')}")
        
        pdf_found = False
        if 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType')
                filename = part.get('filename')
                if mime_type == 'application/pdf' and filename:
                    print(f"     PDF ditemukan: {filename}")
                    pdf_found = True
                    attachment_id = part['body']['attachmentId']
                    
                    try:
                        attachment = service.users().messages().attachments().get(
                            userId='me', messageId=email_id, id=attachment_id).execute()
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        
                        with fitz.open(stream=file_data, filetype="pdf") as doc:
                            for page in doc:
                                resume_text += page.get_text()
                        
                        print(f"     Ekstraksi PDF berhasil. Panjang teks: {len(resume_text)}")
                        break
                    except Exception as pdf_e:
                        print(f"     Gagal mengekstrak teks dari PDF {filename}: {pdf_e}")
                        resume_text = "Gagal mengekstrak teks dari PDF."
        
        if not pdf_found:
            print("     Tidak ada PDF ditemukan. Hanya akan mengekstrak info dari PDF.")
            return {"name": "Tidak Diketahui", "email": "Tidak Diketahui", "resume_text": "Tidak ada lampiran PDF ditemukan."}
        
        if not resume_text.strip():
            print("Peringatan: Teks resume dari PDF kosong setelah ekstraksi.")
            return {"name": "Tidak Diketahui", "email": "Tidak Diketahui", "resume_text": "Teks PDF tidak dapat diekstrak atau kosong."}
        
        resume_text = clean_resume_text(resume_text)
        
        name_patterns = [
            r'(?:nama|name)[:\s]*([A-Za-z\s]+)(?:\n|$)',
            r'^([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\n|$)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s+[\w@.+]+@',  
            r'^([A-Z\s]+)(?:\n|$)',  
        ]
        
        extracted_name = "Tidak Diketahui"
        for pattern in name_patterns:
            name_match = re.search(pattern, resume_text, re.IGNORECASE | re.MULTILINE)
            if name_match:
                extracted_name = name_match.group(1).strip()
                extracted_name = re.sub(r'[\d\W_]+$', '', extracted_name).strip()
                extracted_name = re.sub(r'@[^\s]+', '', extracted_name).strip()
                
                if ' ' in extracted_name and len(extracted_name.split()) >= 2:
                    break
    
                elif len(extracted_name.split()) == 1 and len(extracted_name) > 3:
                    lines = resume_text.split('\n')
                    for i, line in enumerate(lines):
                        if extracted_name in line and i + 1 < len(lines):
                            next_line = lines[i + 1].strip()
                            if re.match(r'^[A-Za-z\s]+$', next_line):
                                extracted_name += ' ' + next_line
                                break
                    break
        
        if extracted_name == "Tidak Diketahui":
            first_line = resume_text.split('\n')[0].strip()
            if re.match(r'^[A-Za-z\s]+$', first_line) and len(first_line.split()) >= 2:
                extracted_name = first_line

        extracted_name = clean_extracted_name(extracted_name)
 
        email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resume_text)
        extracted_email = email_match.group(0).strip() if email_match else "tidak_ada@email.com"

        if "@" not in extracted_email or "." not in extracted_email or " " in extracted_email:
            extracted_email = "tidak_valid@email.com"

        if extracted_name == "Tidak Diketahui" and extracted_email != "tidak_valid@email.com":
            email_name = extracted_email.split('@')[0]
            email_name = re.sub(r'[^a-zA-Z]', ' ', email_name)
            email_name = ' '.join([word.capitalize() for word in email_name.split()])
            extracted_name = email_name

        print(f"Nama diekstrak dari PDF: '{extracted_name}', Email diekstrak dari PDF: '{extracted_email}'")
        return {"name": extracted_name, "email": extracted_email, "resume_text": resume_text}
    except HttpError as err:
        print(f"Error mengekstrak info dari email {email_id}: {err.content.decode('utf-8')}")
        return {"name": "Error", "email": "Error", "resume_text": f"Error: {err.content.decode('utf-8')}"}
    except Exception as e:
        print(f"Error umum mengekstrak info dari email {email_id}: {e}")
        return {"name": "Error", "email": "Error", "resume_text": f"Error umum: {str(e)}"}
    
def _summarize_resume_logic(resume_text: str) -> str:
    """
    Menggunakan LLM untuk meringkas teks resume yang panjang menjadi beberapa poin penting.
    Hasil ringkasan lebih rapi dan terstruktur.
    """
    llm = ChatGoogleGenerativeAI(model="models/gemini-1.5-flash-latest", temperature=0.2)
    
    summarize_prompt = PromptTemplate.from_template(
        "Tolong buat ringkasan PADAT dan RAPI dari resume berikut. "
        "Fokus pada poin-poin utama dengan format yang terstruktur:\n"
        "1. Pengalaman Kerja (perusahaan, jabatan, durasi, pencapaian utama)\n"
        "2. Keterampilan Teknis (bahasa pemrograman, tools, framework)\n" 
        "3. Pendidikan (gelar, universitas, tahun, IPK jika ada)\n"
        "4. Sertifikasi (jika ada)\n"
        "5. Kemampuan Bahasa (jika ada)\n\n"
        "Gunakan bullet points dan format yang konsisten.\n"
        "Hapus informasi yang duplikat atau tidak relevan.\n"
        "Tulis dalam bahasa Indonesia yang baik dan benar.\n\n"
        "Resume:\n{resume_text}\n\n"
        "Ringkasan Rapi:"
    )
    
    summarize_chain = summarize_prompt | llm
    
    try:
        if not resume_text or len(resume_text) < 100:
            return "Informasi resume tidak cukup untuk dibuat ringkasan."
            
        result = summarize_chain.invoke({"resume_text": resume_text})
        return result.content.strip()
    except Exception as e:
        print(f"Error saat meringkas resume oleh LLM: {e}")
        return "Gagal membuat ringkasan resume."

def _simple_summarize_resume(resume_text: str) -> str:
    """
    Fallback summarization manual jika AI gagal.
    """
    experience_match = re.search(r'(?:pengalaman|experience).*?(\d+[\+\s]tahun|tahun)', resume_text, re.IGNORECASE)
    skills_match = re.findall(r'(python|sql|machine learning|deep learning|tensorflow|pandas|numpy|scikit)', resume_text, re.IGNORECASE)
    education_match = re.search(r'(?:pendidikan|education).*?(s[12]|d3|d4|sarjana|magister|diploma)', resume_text, re.IGNORECASE)
    
    summary = "Ringkasan:\n"
    
    if experience_match:
        summary += f"• Pengalaman: {experience_match.group(0)}\n"
    
    if skills_match:
        unique_skills = list(set([s.title() for s in skills_match]))
        summary += f"• Keterampilan: {', '.join(unique_skills[:5])}\n"
    
    if education_match:
        summary += f"• Pendidikan: {education_match.group(0)}\n"
    
    return summary
        
def _analyze_and_screen_resume_logic(job_description: str, resume_text: str) -> str:
    """
    Menganalisis resume menggunakan model AI.
    Mengembalikan 'SANGAT COCOK', 'COCOK', atau 'KURANG COCOK'.
    """
    llm = ChatGoogleGenerativeAI(model="models/gemini-1.5-flash-latest", temperature=0.2) 
    
    screening_prompt = PromptTemplate.from_template(
        "Anda adalah seorang perekrut ahli. "
        "Bandingkan resume berikut dengan deskripsi pekerjaan yang diberikan. "
        "Berikan penilaian kecocokan berdasarkan seberapa baik kualifikasi, pengalaman, dan keterampilan di resume "
        "sesuai dengan persyaratan pekerjaan. "
        "Balas HANYA dengan SATU kata berikut: 'SANGAT_COCOK', 'COCOK', atau 'KURANG_COCOK'.\n\n"
        "JANGAN gunakan kata lain selain tiga pilihan tersebut.\n\n"
        "Deskripsi Pekerjaan: {job_description}\n\n"
        "Resume:\n{resume_text}\n\n"
        "Penilaian Kecocokan:"
    )
    
    screening_chain = screening_prompt | llm
    
    try:
        result = screening_chain.invoke({"job_description": job_description, "resume_text": resume_text})
        screening_output = result.content.strip().upper()
        
        print(f"RAW AI RESPONSE: '{screening_output}'")  

        if "SANGAT_COCOK" in screening_output:
            return "SANGAT COCOK"
        elif "COCOK" in screening_output:
            return "COCOK"
        elif "KURANG_COCOK" in screening_output:
            return "KURANG COCOK"
        else:
            print("AI response tidak expected, default ke COCOK")
            return "COCOK"
            
    except Exception as e:
        print(f"Error saat screening resume oleh LLM: {e}")
        return "COCOK"  

def _find_available_slot_logic():
    """
    Mencari slot waktu yang tersedia untuk wawancara dengan MEMBACA JADWAL YANG SUDAH ADA.
    Mengembalikan string datetime dalam format yang rapi dengan zona waktu.
    """
    try:
        service = get_google_services()['calendar']
        wib_tz = datetime.timezone(datetime.timedelta(hours=7))
        time_min = datetime.datetime.now(wib_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + datetime.timedelta(days=7)
        events_result = service.events().list(
            calendarId='primary',
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        existing_events = events_result.get('items', [])

        working_hours_start = 9
        working_hours_end = 17
        slot_duration = datetime.timedelta(hours=1)

        current_date = time_min + datetime.timedelta(days=1)
        found_slot = None

        while current_date < time_max and not found_slot:
            if current_date.weekday() >= 5:
                current_date += datetime.timedelta(days=1)
                continue

            current_time = current_date.replace(hour=working_hours_start, minute=0, second=0, microsecond=0)
            end_of_day = current_date.replace(hour=working_hours_end, minute=0, second=0, microsecond=0)

            while current_time < end_of_day and not found_slot:
                slot_end = current_time + slot_duration

                is_available = True
                for event in existing_events:
                    event_start_str = event['start'].get('dateTime', event['start'].get('date'))
                    event_end_str = event['end'].get('dateTime', event['end'].get('date'))

                    event_start = parser.parse(event_start_str)
                    event_end = parser.parse(event_end_str)
                    if (current_time < event_end) and (slot_end > event_start):
                        is_available = False
                        break

                if is_available:
                    found_slot = current_time
                    break

                current_time += slot_duration

            if not found_slot:
                current_date += datetime.timedelta(days=1)

        if found_slot:
            formatted_time = found_slot.strftime('%Y-%m-%d pukul %H:%M WIB')
            return formatted_time
        else:
            return "Tidak ada slot kosong yang ditemukan dalam 7 hari ke depan."

    except Exception as e:
        print(f"Error mencari slot wawancara: {e}")
        fallback_time = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        formatted_time = fallback_time.strftime('%Y-%m-%d pukul %H:%M WIB')
        return formatted_time

def _schedule_interview_logic(candidate_email: str, candidate_name: str, interview_time: str) -> str:
    """
    Menjadwalkan wawancara di Google Calendar.
    """
    try:
        service = get_google_services()['calendar']
        
        if "pukul" in interview_time and "WIB" in interview_time:
            date_str = interview_time.split(" pukul ")[0]
            time_str = interview_time.split(" pukul ")[1].replace(" WIB", "")
            datetime_str = f"{date_str}T{time_str}:00+07:00"  
            start_time = parser.parse(datetime_str)
            end_time = start_time + datetime.timedelta(hours=1)
        else:
            # Fallback untuk format lama
            start_time = parser.parse(interview_time)
            end_time = start_time + datetime.timedelta(hours=1)
        
        event = {
            'summary': f'Wawancara {candidate_name}',
            'description': f'Wawancara untuk posisi Data Scientist dengan {candidate_name}',
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Jakarta',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Jakarta',
            },
            'attendees': [
                {'email': candidate_email},
                {'email': 'ISI_EMAIL_PERUSAHAAN'},
            ],
            'reminders': {
                'useDefault': True,
            },
        }
        
        event = service.events().insert(calendarId='primary', body=event).execute()
        return f"Wawancara berhasil dijadwalkan untuk {candidate_name} pada {interview_time}"
        
    except Exception as e:
        print(f"Error menjadwalkan wawancara: {e}")
        return f"Gagal menjadwalkan wawancara: {str(e)}"

def test_sheets_connection():
    """Test koneksi ke Google Sheets"""
    try:
        SPREADSHEET_ID = 'ID_SHEET_ANDA'
        service = get_google_services()['sheets']
        
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range='Sheet1!A1:E1').execute()
        
        print("Koneksi Google Sheets BERHASIL")
        print("Data yang ada:", result.get('values', []))
        return True
    except Exception as e:
        print(f"Koneksi Google Sheets GAGAL: {e}")
        return False

def _add_to_approved_candidates_sheet_logic(candidate_name: str, candidate_email: str, interview_schedule: str, screening_result: str, resume_text: str) -> str:
    """
    Logika inti untuk menambahkan data kandidat ke Google Sheets.
    Menyertakan teks resume yang diekstrak.
    """
    SPREADSHEET_ID = 'ID_SHEET_ANDA'
    service = get_google_services()['sheets']
    range_name = 'Sheet1!A:E'

    clean_name = ' '.join(candidate_name.split()[:3])  

    if len(resume_text) > 10000:
        resume_text = resume_text[:10000] + "... [truncated]"

    clean_screening = screening_result.replace("_", " ").title()
    
    values = [[clean_name, candidate_email, interview_schedule, clean_screening, resume_text]]
    body = {'values': values}
    
    try:
        print(f"Menambahkan ke Sheets: {clean_name}, {candidate_email}, {interview_schedule}")
        result = service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID, 
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body).execute()
        
        print(f"Data kandidat {clean_name} berhasil ditambahkan ke Google Sheets.")
        print(f"Update range: {result.get('updates', {}).get('updatedRange')}")
        return f"Data kandidat {clean_name} berhasil ditambahkan ke Google Sheets."
    except HttpError as err:
        error_msg = err.content.decode('utf-8')
        print(f"Gagal menambahkan data ke Google Sheets: {error_msg}")
        return f"Gagal menambahkan data ke Google Sheets: {error_msg}"
    except Exception as e:
        print(f"Error umum saat menambahkan data ke Sheets: {e}")
        return f"Error umum saat menambahkan data ke Sheets: {str(e)}"
    
def _send_email_reply_logic(recipient: str, subject: str, body: str) -> str:
    """
    Logika inti untuk mengirim email balasan ke pelamar.
    """
    try:
        service = get_google_services()['gmail']
        message = MIMEText(body)
        message['to'] = recipient
        message['subject'] = subject
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        service.users().messages().send(userId='me', body={'raw': raw_message}).execute()
        
        return f"Email balasan berhasil dikirim ke {recipient} dengan subjek: {subject}"
    except HttpError as err:
        error_msg = err.content.decode('utf-8')
        print(f"Gagal mengirim email: {error_msg}")
        return f"Gagal mengirim email: {error_msg}. Pastikan izin email sudah benar dan alamat penerima valid."

def get_list_of_emails():
    """Mengambil daftar semua email lamaran, terlepas dari status dibaca/belum dibaca,
       dan menyertakan status 'Dibaca'/'Belum Dibaca'."""
    try:
        service = get_google_services()['gmail']
        results = service.users().messages().list(userId='me', q='subject:"Lamaran Pekerjaan"').execute()
        messages = results.get('messages', [])
        
        if not messages:
            return []
        
        email_list = []
        for msg in messages:
            try:
                full_msg = service.users().messages().get(userId='me', id=msg['id'], format='full').execute()
                
                headers = full_msg['payload']['headers']
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Tidak Diketahui')
                sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Tidak Diketahui')
                
                is_unread = 'UNREAD' in full_msg.get('labelIds', [])
                status = 'Belum Dibaca' if is_unread else 'Dibaca'
                print(f"Email ID: {msg['id']}, Labels: {full_msg.get('labelIds', [])}, Status: {status}")
                
                email_list.append({'id': msg['id'], 'subject': subject, 'from': sender, 'status': status})
            except Exception as e:
                print(f"Error mengambil detail email {msg.get('id', 'N/A')}: {e}")
                email_list.append({'id': msg.get('id', 'N/A'), 'subject': 'Error mengambil subjek', 'from': 'Error mengambil pengirim', 'status': 'Error'})
        return email_list
    except HttpError as err:
        print(f"Error mengambil daftar email: {err.content.decode('utf-8')}")
        return {"error": f"Gagal mengambil daftar email: {err.content.decode('utf-8')}"}
    except Exception as e:
        print(f"Error umum saat mengambil daftar email: {str(e)}")
        return {"error": f"Terjadi kesalahan saat mengambil daftar email: {str(e)}"}

def get_sheet_data():
    """Mengambil semua data dari Google Sheet."""
    SPREADSHEET_ID = 'ID_SHEET_ANDA'
    service = get_google_services()['sheets']
    range_name = 'Sheet1!A:E'
    
    try:
        print(f"Mengambil data dari Google Sheets: {SPREADSHEET_ID}, Range: {range_name}...")
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name).execute()
        
        values = result.get('values', [])
        print(f"Data dari Google Sheets berhasil diambil. Jumlah baris: {len(values)}")
        return values
    except HttpError as err:
        error_msg = err.content.decode('utf-8')
        print(f"Error mengambil data sheet: {error_msg}")
        return {"error": f"Gagal mengambil data dari Google Sheet: {error_msg}"}
    except Exception as e:
        print(f"Error umum saat mengambil data sheet: {str(e)}")
        return {"error": f"Terjadi kesalahan saat mengambil data sheet: {str(e)}"}


@tool
def get_new_job_applications_tool() -> list[str]:
    """
    Mengambil email lamaran pekerjaan baru dari Gmail.
    Email dianggap sebagai lamaran jika subjeknya 'Lamaran Pekerjaan'.
    Hanya mengambil email yang BELUM DIBACA.
    Mengembalikan daftar ID email yang ditemukan.
    """
    return _get_new_job_applications_logic()

@tool
def extract_applicant_info_from_email_id_tool(email_id: str) -> dict:
    """
    Mengambil konten dari email, termasuk lampiran PDF jika ada, dan mengekstrak info pelamar.
    Menggunakan regex untuk mengekstrak NAMA dan ALAMAT EMAIL secara langsung.
    Mengembalikan dict dengan keys 'name', 'email', 'resume_text'.
    """
    return _extract_applicant_info_from_email_id_logic(email_id)

@tool
def analyze_and_screen_resume_tool(job_description: str, resume_text: str) -> str:
    """
    Menganalisis resume untuk menentukan kecocokannya dengan deskripsi pekerjaan menggunakan model AI.
    Mengembalikan 'SANGAT COCOK', 'COCOK', atau 'KURANG COCOK'.
    """
    return _analyze_and_screen_resume_logic(job_description, resume_text)

@tool
def add_to_approved_candidates_sheet_tool(candidate_name: str, candidate_email: str, interview_schedule: str, screening_result: str, resume_text: str) -> str:
    """
    Menambahkan data kandidat ke Google Sheets yang sebenarnya, termasuk hasil screening dan teks resume.
    """
    return _add_to_approved_candidates_sheet_logic(candidate_name, candidate_email, interview_schedule, screening_result, resume_text)

@tool
def send_email_reply_tool(recipient: str, subject: str, body: str) -> str:
    """
    Mengirim email balasan ke pelamar.
    """
    return _send_email_reply_logic(recipient, subject, body)


load_dotenv()
gemini_key = os.getenv("GOOGLE_API_KEY")

if not gemini_key:
    raise ValueError("Error: GOOGLE_API_KEY tidak ditemukan di file .env.")

os.environ["GOOGLE_API_KEY"] = gemini_key
llm = ChatGoogleGenerativeAI(model="models/gemini-1.5-flash-latest", temperature=0)
tools = [
    get_new_job_applications_tool, 
    extract_applicant_info_from_email_id_tool, 
    analyze_and_screen_resume_tool, 
    add_to_approved_candidates_sheet_tool, 
    send_email_reply_tool
]

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", 
         "Anda adalah Asisten HRD yang cerdas. Tugas Anda adalah membantu memproses lamaran pekerjaan. "
         "Gunakan tools yang tersedia untuk mengekstrak informasi, melakukan screening, menjadwalkan, "
         "menambah ke sheet, dan membalas email sesuai instruksi. "
         "Selalu berikan respons yang singkat dan relevan setelah menjalankan tool."),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

def run_agent_process():
    """
    Fungsi utama untuk menjalankan agen HRD.
    Ini adalah fungsi yang akan dipanggil oleh endpoint Flask.
    Mengelola alur kerja dan mengembalikan ringkasan naratif.
    """
    if not test_sheets_connection():
        return json.dumps({
            "summary_message": "Gagal terkoneksi ke Google Sheets. Pastikan ID spreadsheet benar dan izin sudah diberikan.",
            "processed_count": 0, "scheduled_count": 0, "rejected_count": 0
        })
    
    processed_count = 0
    scheduled_count = 0
    rejected_count = 0

    job_description = "Kami mencari Data Scientist dengan pengalaman minimal 2 tahun di bidang machine learning dan deep learning, mahir dalam Python dan SQL, serta memiliki kemampuan komunikasi yang baik."

    try:
        print("\n--- Memeriksa email lamaran baru... ---")
        email_ids = _get_new_job_applications_logic()
        
        if not email_ids:
            print("Tidak ada email lamaran baru yang ditemukan untuk diproses.") 
            return json.dumps({
                "summary_message": "Tidak ada email lamaran baru yang ditemukan untuk diproses.",
                "processed_count": 0, "scheduled_count": 0, "rejected_count": 0
            })

        print(f"Ditemukan {len(email_ids)} email lamaran baru. Memulai pemrosesan...")
        
        for email_id in email_ids:
            print(f"\n--- Memproses email ID: {email_id}... ---") 
            try:
                applicant_info = _extract_applicant_info_from_email_id_logic(email_id)
                candidate_name = applicant_info.get('name')
                candidate_email = applicant_info.get('email')
                full_resume_text = applicant_info.get('resume_text')

                if not candidate_email or candidate_email == "tidak_ada@email.com" or candidate_email == "tidak_valid@email.com":
                    print(f"Lewati email {email_id}: Email tidak valid. Info: {applicant_info}")
                    rejected_count += 1
                    _mark_email_as_read_logic(email_id) 
                    continue

                if not candidate_name or candidate_name == "Tidak Diketahui":
                    candidate_name = candidate_email.split('@')[0]
                    candidate_name = candidate_name.replace('.', ' ').title()
                    print(f"Nama tidak ditemukan, menggunakan email sebagai nama: {candidate_name}")

                if not full_resume_text or full_resume_text == "Tidak ada lampiran PDF ditemukan." or full_resume_text == "Teks PDF tidak dapat diekstrak atau kosong.":
                    print(f"Lewati email {email_id}: Tidak ada lampiran PDF yang dapat diekstrak atau diekstrak sebagai kosong.") 
                    rejected_count += 1
                    _mark_email_as_read_logic(email_id)
                    continue

                processed_count += 1

                print(f"Menganalisis resume untuk {candidate_name}...") 
                screening_result = _analyze_and_screen_resume_logic(job_description, full_resume_text)
                print(f"Hasil screening untuk {candidate_name}: '{screening_result}'")

                print("Membuat ringkasan resume...")
                summarized_resume = _summarize_resume_logic(full_resume_text)

                if len(summarized_resume) < 50 or "gagal" in summarized_resume.lower():
                    print("AI summarization gagal, menggunakan fallback...")
                    summarized_resume = _simple_summarize_resume(full_resume_text)
                
                print(f"Ringkasan resume berhasil dibuat. Panjang: {len(summarized_resume)} karakter.")

                if screening_result == 'KURANG COCOK':
                    print(f"Kandidat {candidate_name} kurang cocok. Menolak lamaran...")
                    rejected_count += 1

                    add_to_sheet_status = _add_to_approved_candidates_sheet_logic(
                        candidate_name, 
                        candidate_email, 
                        "", 
                        "Ditolak", 
                        summarized_resume
                    )
                    print(add_to_sheet_status)
                    
                    rejection_subject = "Update Lamaran Pekerjaan"
                    rejection_body = f"Halo {candidate_name},\n\n" \
                                     f"Terima kasih atas minat Anda untuk bergabung dengan tim kami. Setelah meninjau lamaran Anda, " \
                                     f"kami mohon maaf untuk menginformasikan bahwa kami tidak dapat melanjutkan proses seleksi untuk Anda saat ini.\n\n" \
                                     f"Kami menghargai waktu dan usaha Anda. Semoga sukses di masa depan!\n\n" \
                                     f"Salam,\nTim HRD"
                    email_status = _send_email_reply_logic(candidate_email, rejection_subject, rejection_body)
                    print(email_status)
                    
                    _mark_email_as_read_logic(email_id)
                    
                else:  
                    print(f"Kandidat {candidate_name} cocok. Mencari slot wawancara...") 
                    interview_time = _find_available_slot_logic() 
                    
                    if interview_time and "Gagal" not in interview_time and "Tidak ada slot kosong" not in interview_time and "error" not in interview_time.lower():
                        print(f"Slot tersedia: {interview_time}. Menjadwalkan wawancara untuk {candidate_name}...") 
                        schedule_status = _schedule_interview_logic(candidate_email, candidate_name, interview_time)
                        
                        if "berhasil dijadwalkan" in schedule_status.lower():
                            print(f"Wawancara dijadwalkan untuk {candidate_name} pada {interview_time}.") 

                            try:
                                if "pukul" in interview_time and "WIB" in interview_time:
                                    date_part = interview_time.split(" pukul ")[0]
                                    time_part = interview_time.split(" pukul ")[1].replace(" WIB", "")
                                    interview_date = datetime.datetime.strptime(date_part, '%Y-%m-%d')
                                    formatted_date = interview_date.strftime('%d %B %Y') 
                                    email_time_display = f"{formatted_date} pukul {time_part} WIB"
                                else:
                                    email_time_display = interview_time
                            except:
                                email_time_display = interview_time

                            add_to_sheet_status = _add_to_approved_candidates_sheet_logic(
                                candidate_name, 
                                candidate_email, 
                                interview_time, 
                                "Jadwalkan Wawancara", 
                                summarized_resume
                            )
                            print(add_to_sheet_status)
                            
                            interview_subject = "Undangan Wawancara untuk Posisi Data Scientist"
                            interview_body = f"Halo {candidate_name},\n\n" \
                                             f"Terima kasih atas lamaran Anda. Kami ingin mengundang Anda untuk wawancara terkait posisi Data Scientist pada:\n\n" \
                                             f"Tanggal: {email_time_display}\n\n" \
                                             f"Kami akan mengirimkan link meeting secara terpisah.\n\n" \
                                             f"Salam,\nTim HRD"
                            email_status = _send_email_reply_logic(candidate_email, interview_subject, interview_body)
                            print(email_status)
                            scheduled_count += 1
                            _mark_email_as_read_logic(email_id)
                        else:
                            print(f"Gagal menjadwalkan wawancara untuk {candidate_name}.")
                            rejected_count += 1
                            _mark_email_as_read_logic(email_id)
                    else:
                        print(f"Tidak ada slot wawancara yang tersedia untuk {candidate_name}.")
                        rejected_count += 1
                        _mark_email_as_read_logic(email_id)
                    
            except Exception as e:
                print(f"Kesalahan fatal saat memproses email {email_id}: {e}")
                _mark_email_as_read_logic(email_id)
                continue
    
    except Exception as e:
        print(f"Kesalahan umum dalam proses utama: {e}")
        return json.dumps({
            "summary_message": f"Terjadi kesalahan dalam proses: {str(e)}",
            "processed_count": processed_count, "scheduled_count": scheduled_count, "rejected_count": rejected_count
        })

    summary_message = f"Proses agen HRD selesai. Jumlah email diproses: {processed_count}. Berhasil dijadwalkan: {scheduled_count}. Ditolak: {rejected_count}."
    print("\n--- Proses Selesai ---") 
    print(summary_message) 

    return json.dumps({
        "summary_message": summary_message,
        "processed_count": processed_count,
        "scheduled_count": scheduled_count,
        "rejected_count": rejected_count
    })

def test_nabira_screening():
    """Test screening untuk CV XXXX"""
    job_description = "Kami mencari Data Scientist dengan pengalaman minimal 2 tahun di bidang machine learning dan deep learning, mahir dalam Python dan SQL, memiliki kemampuan komunikasi yang baik, memiliki IPK minimal 3.25 dari universitas, serta memiliki kompetensi  bahasa Inggris."

    XXX_cv = """
    XXXX
    Data Scientist dengan pengalaman 2+ tahun di machine learning dan deep learning.
    Mahir dalam Python dan SQL. memiliki kemampuan komunikasi yang excellent.
    
    PENGALAMAN:
    - Data Scientist di PT. Teknologi AI Indonesia (2022-Sekarang)
    - Junior Machine Learning Engineer di StartUp AI Solutions (2020-2021)
    
    SKILLS:
    Python, SQL, TensorFlow, Keras, Machine Learning, Deep Learning
    """
    
    print("=== TEST SCREENING CV NABIRA ===")
    result = _analyze_and_screen_resume_logic(job_description, XXX_cv)
    print(f"Hasil: {result}")
    
    if result == 'KURANG COCOK':
        print("STATUS: DITOLAK")
    else:
        print("STATUS: DITERIMA")

def test_summarization():
    """Test summarization dengan CV contoh"""
    test_cv = """
    XXX
    Data Scientist dengan pengalaman 2+ tahun di machine learning dan deep learning.
    Mahir dalam Python dan SQL. memiliki kemampuan komunikasi yang excellent.
    
    PENGALAMAN:
    - Data Scientist di PT. Teknologi AI Indonesia (2022-Sekarang)
    - Junior Machine Learning Engineer di StartUp AI Solutions (2020-2021)
    
    SKILLS:
    Python, SQL, TensorFlow, Keras, Machine Learning, Deep Learning
    
    PENDIDIKAN:
    S1 Teknik Informatika, ITB (2016-2020), IPK 3.85
    """
    
    print("=== TEST SUMMARIZATION ===")
    result = _summarize_resume_logic(test_cv)
    print("Hasil Summarization:")
    print(result)
    
    # Test cleaning
    cleaned = clean_resume_text(test_cv)
    print("\nHasil Cleaning:")
    print(cleaned)

def manual_test_sheets():
    """Test manual untuk Google Sheets"""
    print("Testing Google Sheets connection...")
    if test_sheets_connection():
        print("Testing data insertion...")
        result = _add_to_approved_candidates_sheet_logic(
            "Test Candidate", 
            "test@email.com", 
            "2024-01-15 pukul 10:00 WIB", 
            "TEST", 
            "This is a test resume content for Google Sheets integration test."
        )
        print("Result:", result)
        
        data = get_sheet_data()
        print("Data di sheets:", data)
    else:
        print("Connection failed. Please check spreadsheet ID and permissions.")

if __name__ == "__main__":
    test_nabira_screening()
    test_summarization()