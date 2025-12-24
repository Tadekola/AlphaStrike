# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# We add build-essential in case some packages need compilation (though mostly unnecessary for the current reqs, it's safe)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Expose port 8501 for Streamlit
EXPOSE 8501

# Define environment variable to ensure Streamlit runs in headless mode
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Run app_streamlit.py when the container launches
CMD ["streamlit", "run", "app_streamlit.py"]
