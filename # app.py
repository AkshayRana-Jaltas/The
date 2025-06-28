import os
from pathlib import Path
from flask import Flask, render_template, jsonify, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import openai
import requests
from bs4 import BeautifulSoup
import schedule
import time
import random
from datetime import datetime
from threading import Thread
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import json

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize rate limiter
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configuration
CONFIG = {
    'CONTENT_DIR': Path("content"),
    'LOG_FILE': Path("app.log"),
    'MAX_LOG_SIZE': 1024 * 1024,  # 1MB
    'BACKUP_COUNT': 5,
    'DEFAULT_TOPICS': ["technology", "science", "history", "creative writing"],
    'DEFAULT_STYLES': ["newspaper article", "blog post", "short story", "research summary"],
    'SCHEDULE_TIME': "09:00",  # Daily generation time
    'MAX_RESEARCH_LENGTH': 1000,
    'CONTENT_LENGTH_RANGE': (500, 700),
    'TEMP': 0.7,
    'MODEL': "gpt-3.5-turbo"
}

# Setup directories
CONFIG['CONTENT_DIR'].mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            CONFIG['LOG_FILE'],
            maxBytes=CONFIG['MAX_LOG_SIZE'],
            backupCount=CONFIG['BACKUP_COUNT']
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
openai.api_key = os.getenv('OPENAI_API_KEY')
if not openai.api_key:
    logger.error("OpenAI API key not configured!")
    raise ValueError("OpenAI API key missing")

class ContentGenerator:
    """Handles content generation and management"""
    
    def __init__(self):
        self.topics = self._load_custom_topics() or CONFIG['DEFAULT_TOPICS']
        self.styles = self._load_custom_styles() or CONFIG['DEFAULT_STYLES']
    
    def _load_custom_topics(self):
        """Load custom topics from file if exists"""
        try:
            with open('custom_topics.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
    
    def _load_custom_styles(self):
        """Load custom styles from file if exists"""
        try:
            with open('custom_styles.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
    
    def research_topic(self, topic):
        """Web research function with improved error handling and encoding"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'en-US,en;q=0.5'
            }
            url = f"https://en.wikipedia.org/wiki/{topic.replace(' ', '_')}"
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Handle encoding properly
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.content, 'html.parser')
            
            content_div = soup.find('div', {'id': 'mw-content-text'})
            if content_div:
                # Clean up text by removing excessive whitespace and references
                text = ' '.join(content_div.get_text().split())
                return f"Wikipedia Context: {text[:CONFIG['MAX_RESEARCH_LENGTH']]}"
            return f"Basic information about {topic}"
        except requests.RequestException as e:
            logger.error(f"Research request failed: {e}")
            return f"General knowledge about {topic}"
        except Exception as e:
            logger.error(f"Research error: {e}")
            return f"Background information about {topic}"
    
    def generate_content(self, topic, style):
        """Improved AI content generation with better error handling"""
        research = self.research_topic(topic)
        
        prompt = f"""
        Write a {style} about {topic} using this research context: {research}.
        
        Requirements:
        - {CONFIG['CONTENT_LENGTH_RANGE'][0]}-{CONFIG['CONTENT_LENGTH_RANGE'][1]} words
        - Natural human writing style with personality
        - Varied sentence structure and paragraph length
        - Rich, precise vocabulary appropriate for the topic
        - Flawless grammar and punctuation
        - Include a compelling, attention-grabbing title
        - Maintain consistent tone throughout
        - Add relevant examples or analogies where appropriate
        
        Format:
        [Title: Your Creative Title Here]
        [Content: Your article content here...]
        """
        
        try:
            response = openai.ChatCompletion.create(
                model=CONFIG['MODEL'],
                messages=[{"role": "user", "content": prompt}],
                temperature=CONFIG['TEMP'],
                max_tokens=1500,
                request_timeout=30  # Add timeout
            )
            return response.choices[0].message.content
        except openai.error.APIError as e:
            logger.error(f"OpenAI API error: {e}")
        except openai.error.Timeout as e:
            logger.error(f"OpenAI timeout error: {e}")
        except openai.error.ServiceUnavailableError as e:
            logger.error(f"OpenAI service unavailable: {e}")
        except Exception as e:
            logger.error(f"Unexpected generation error: {e}")
        
        return self._fallback_content(topic)
    
    def _fallback_content(self, topic):
        """Provide fallback content when generation fails"""
        return f"Title: Sample Article About {topic}\n\nThis is a sample fallback content about {topic}."

    def save_content(self, content, topic):
        """Save content to file with metadata"""
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = CONFIG['CONTENT_DIR'] / f"{timestamp}_{topic.replace(' ', '_')}.txt"
            
            # Add metadata to content
            full_content = f"Generated: {timestamp}\nTopic: {topic}\n\n{content}"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(full_content)
            return filename
        except OSError as e:
            logger.error(f"File save error: {e}")
            return None
    
    def get_latest_content(self, count=5):
        """Get latest generated content files"""
        try:
            files = sorted(CONFIG['CONTENT_DIR'].iterdir(), key=os.path.getmtime, reverse=True)
            return [f.name for f in files][:count]
        except OSError as e:
            logger.error(f"Error listing content files: {e}")
            return []

# Initialize content generator
content_gen = ContentGenerator()

def daily_content_job():
    """Scheduled content generation task"""
    logger.info("Running daily content generation job")
    try:
        topic = random.choice(content_gen.topics)
        style = random.choice(content_gen.styles)
        logger.info(f"Generating content about '{topic}' in style '{style}'")
        
        content = content_gen.generate_content(topic, style)
        filename = content_gen.save_content(content, topic)
        
        if filename:
            logger.info(f"Successfully generated content: {filename}")
        else:
            logger.error("Failed to save generated content")
    except Exception as e:
        logger.error(f"Daily job failed: {e}")

# Flask routes
@app.route('/')
def home():
    """Render homepage with latest content"""
    latest_files = content_gen.get_latest_content(3)
    latest_content = []
    
    for file in latest_files:
        try:
            filepath = CONFIG['CONTENT_DIR'] / file
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                latest_content.append({
                    'filename': file,
                    'title': content.split('\n')[0] if content else 'Untitled',
                    'preview': ' '.join(content.split('\n')[3:])[:200] + '...' if content else ''
                })
        except UnicodeDecodeError:
            try:
                with open(filepath, 'r', encoding='latin-1') as f:
                    content = f.read()
                    latest_content.append({
                        'filename': file,
                        'title': content.split('\n')[0] if content else 'Untitled',
                        'preview': ' '.join(content.split('\n')[3:])[:200] + '...' if content else ''
                    })
            except Exception as e:
                logger.error(f"Failed to read file {file} with fallback encoding: {e}")
        except Exception as e:
            logger.error(f"Error reading file {file}: {e}")
    
    return render_template('index.html', latest_content=latest_content)

@app.route('/generate', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def generate_now():
    """Generate content immediately"""
    try:
        topic = random.choice(content_gen.topics)
        style = random.choice(content_gen.styles)
        content = content_gen.generate_content(topic, style)
        filename = content_gen.save_content(content, topic)
        
        # Parse the generated content
        title = content.split('\n')[0].replace('Title: ', '') if content else 'Untitled'
        body = '\n'.join(content.split('\n')[1:]) if content else 'No content generated'
        
        return jsonify({
            'status': 'success' if filename else 'partial_success',
            'topic': topic,
            'style': style,
            'title': title,
            'content': body,
            'filename': filename,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Generation endpoint error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/content/<filename>')
def get_content(filename):
    """Serve generated content files with security checks"""
    try:
        # Security check to prevent directory traversal
        if '..' in filename or filename.startswith('/'):
            raise ValueError("Invalid filename")
            
        filepath = CONFIG['CONTENT_DIR'] / filename
        
        # Verify file exists and is in the content directory
        if not filepath.is_file():
            raise FileNotFoundError
        
        return send_from_directory(
            CONFIG['CONTENT_DIR'],
            filename,
            mimetype='text/plain',
            as_attachment=False
        )
    except Exception as e:
        logger.error(f"Content retrieval error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 404

@app.route('/content/list')
def list_content():
    """List available content files"""
    try:
        files = content_gen.get_latest_content(20)
        return jsonify({
            'status': 'success',
            'count': len(files),
            'files': files
        })
    except Exception as e:
        logger.error(f"Content listing error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def run_scheduler():
    """Run scheduler in background thread"""
    schedule.every().day.at(CONFIG['SCHEDULE_TIME']).do(daily_content_job)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == '__main__':
    # Verify content directory is writable
    try:
        test_file = CONFIG['CONTENT_DIR'] / 'test.txt'
        test_file.write_text("test", encoding='utf-8')
        test_file.unlink()
    except Exception as e:
        logger.error(f"Failed to initialize content directory: {e}")
        raise

    # Initial content generation if directory is empty
    if not any(CONFIG['CONTENT_DIR'].iterdir()):
        logger.info("No content found - generating initial content")
        daily_content_job()
    
    # Start scheduler thread
    scheduler_thread = Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    # Start Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
    # Replace the load_dotenv() line near the top of your file with:
try:
    load_dotenv(encoding='utf-8')  # Explicitly specify UTF-8 encoding
except UnicodeDecodeError:
    # If UTF-8 fails, try with latin-1 as fallback
    load_dotenv(encoding='latin-1')