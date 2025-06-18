import os
import fitz  
import numpy as np
import faiss
import json
import requests
from sentence_transformers import SentenceTransformer


PDF_FOLDER = "pdfs"
API_KEY = "AIzaSyATwH943SZeBseHDCECEFJvBnvxFZpPjYU"  
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={API_KEY}"


def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def split_text(text, chunk_size=500):
    sentences = text.split(". ")
    chunks, current_chunk = [], ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < chunk_size:
            current_chunk += sentence + ". "
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence + ". "
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


def load_pdfs(folder):
    all_chunks = []
    for filename in os.listdir(folder):
        if filename.endswith(".pdf"):
            path = os.path.join(folder, filename)
            print(f"📄 Processing: {filename}")
            text = extract_text_from_pdf(path)
            chunks = split_text(text)
            all_chunks.extend(chunks)
    print(f" Total chunks created: {len(all_chunks)}")
    return all_chunks


def build_faiss_index(chunks, model):
    print(" Creating embeddings...")
    embeddings = model.encode(chunks, show_progress_bar=True)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings))
    return index, embeddings


def search_index(query, model, chunks, index, k=5):
    query_embedding = model.encode([query])
    distances, indices = index.search(np.array(query_embedding), k)
    return [chunks[i] for i in indices[0]]


def ask_gemini(question, model, chunks, index):
    relevant_chunks = search_index(question, model, chunks, index)
    context = "\n\n".join(relevant_chunks)
    prompt = f"You are an assistant answering questions about company annual reports. Use the following context:\n\n{context}\n\nQuestion: {question}\nAnswer:"

    data = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    response = requests.post(API_URL, headers={"Content-Type": "application/json"}, data=json.dumps(data))

    if response.status_code == 200:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        return f" Error {response.status_code}: {response.text}"


def main():
    print(" Loading PDFs...")
    chunks = load_pdfs(PDF_FOLDER)

    model = SentenceTransformer("all-MiniLM-L6-v2")
    index, _ = build_faiss_index(chunks, model)

    print("\n Chatbot ready! Type 'exit' to quit.\n")
    while True:
        question = input("You: ")
        if question.lower() in ["exit", "quit"]:
            print(" Goodbye!")
            break
        response = ask_gemini(question, model, chunks, index)
        print("Gemini:", response)

if __name__ == "__main__":
    main()
