from flask import Flask, jsonify, render_template, request
from hr_agent_real import run_agent_process, get_list_of_emails, get_sheet_data
import json
import logging

# Inisialisasi aplikasi Flask
app = Flask(__name__)

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@app.route('/')
def home():
    """Endpoint untuk menampilkan halaman HTML."""
    return render_template('index.html')

@app.route('/run-hr-agent', methods=['POST'])
def run_hr_agent_endpoint():
    """Endpoint API untuk menjalankan agen HRD."""
    try:
        app.logger.info("Menerima permintaan untuk menjalankan agen HRD.")
        output_from_agent_json_string = run_agent_process()
        
        # Mengembalikan respons dengan string JSON dari agen
        return app.response_class(
            response=output_from_agent_json_string,
            status=200,
            mimetype='application/json'
        )
    except Exception as e:
        app.logger.error("Error saat menjalankan agen: %s", str(e), exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Terjadi kesalahan saat menjalankan agen.",
            "error_detail": str(e)
        }), 500

@app.route('/get-emails', methods=['GET'])
def get_emails_endpoint():
    """Endpoint untuk menampilkan daftar email lamaran."""
    try:
        emails = get_list_of_emails()
        if isinstance(emails, dict) and "error" in emails:
            return jsonify(emails), 500
        return jsonify({
            "status": "success",
            "emails": emails
        })
    except Exception as e:
        app.logger.error("Error saat mengambil daftar email: %s", str(e), exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Gagal mengambil daftar email.",
            "error_detail": str(e)
        }), 500

@app.route('/get-sheet-data', methods=['GET'])
def get_sheet_data_endpoint():
    """Endpoint baru untuk menampilkan data dari Google Sheets."""
    try:
        data = get_sheet_data()
        if isinstance(data, dict) and "error" in data:
            return jsonify(data), 500
        return jsonify({
            "status": "success",
            "sheet_data": data
        })
    except Exception as e:
        app.logger.error("Error saat mengambil data sheet: %s", str(e), exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Gagal mengambil data dari Google Sheet.",
            "error_detail": str(e)
        }), 500

# Custom error handler untuk error 500 (Internal Server Error)
@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error("Terjadi error server: %s", str(e), exc_info=True)
    return jsonify({
        "status": "error",
        "message": "Terjadi kesalahan server internal.",
        "error_detail": str(e)
    }), 500

if __name__ == '__main__':
    # Pastikan 'host' disetel ke '0.0.0.0' agar dapat diakses dari luar
    app.run(debug=True, host='0.0.0.0', port=5000)