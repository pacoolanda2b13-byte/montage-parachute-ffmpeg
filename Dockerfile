FROM python:3.11-slim

# FFmpeg + ffprobe (cœur du moteur de montage)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY montage_parachute_ffmpeg.py serveur_api.py ./

# Dossiers de travail (montables en volumes)
RUN mkdir -p /app/sources /app/output
ENV DOSSIER_SOURCES=/app/sources \
    DOSSIER_SORTIE=/app/output \
    PORT=5000

EXPOSE 5000

# Health-check applicatif (Flask + FFmpeg)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/sante').status==200 else 1)" || exit 1

CMD ["python", "serveur_api.py"]
