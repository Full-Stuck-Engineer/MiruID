# MiruID (見るID)

**Self-Hosted Universal ID Card Extraction & Validation Microservice**

> *Miru* (見る) — Japanese for **"to see, inspect, and read."**

**MiruID** is a privacy-first, Dockerized REST API that turns raw photos of national ID cards, driver's licenses, and tax cards into clean, validated JSON. Built with a pluggable hybrid pipeline (**PaddleOCR + Vision/Structured LLMs**) and deterministic country validators—starting with **Indonesian documents (e-KTP, SIM, NPWP)** and architected for global expansion.

## Key Features
- **Hybrid & Pluggable Extraction:** Switch between local `PaddleOCR + LLM` cleanup, direct `Vision-LLM` (OpenAI-compatible / Gemini / Ollama), or `100% Offline OCR` mode via environment variables.
- **Deterministic Country Validators:** Goes beyond raw OCR—validates Indonesian 16-digit NIK regional prefixes, birth date encoding (including female `+40` rules), SIM classes, and dual 15/16-digit NPWP formats.
- **Privacy-First by Design:** Stateless in-memory image processing with zero disk persistence and automatic PII masking in operational logs.
- **Global Plugin Architecture:** Add new countries and document types via isolated schemas and rule validators without touching the core pipeline.

## Author
- **Anthony Febrian** ([@anthonyfebrian](https://github.com/anthonyfebrian) / [@Full-Stuck-Engineer](https://github.com/Full-Stuck-Engineer)) - <anthony.febrian@gmail.com>

## License
This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
