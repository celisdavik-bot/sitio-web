# 1. Traemos un sistema Linux con Python 3.10 ya instalado
FROM python:3.10-slim

# 2. Creamos una carpeta de trabajo dentro del contenedor
WORKDIR /app

# 3. Copiamos nuestra lista de supermercado y compramos los ingredientes
COPY requirements.txt .
RUN pip install -r requirements.txt

# 4. Copiamos TODO el resto de tu código (app.py, bases de datos, etc.)
COPY . .

# 5. Abrimos el puerto 5000 (el que usa tu web)
EXPOSE 5000

# 6. La orden final para encender la aplicación
CMD ["python", "app.py"]