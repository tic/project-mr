FROM python:3.11-slim

# Install system dependencies for spotdl
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY beatman/ ./beatman/

# Expose Flask port
EXPOSE 5000

# Run the application
# CMD ["pwd"]
# CMD ["ls", "-al", "."]
# CMD ["ls", "-al", "beatman"]
CMD ["python","-m", "beatman"]
