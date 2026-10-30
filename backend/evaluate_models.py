"""Small repeatable model comparison harness. Run only with permitted provider credentials."""
import csv, os, time
from pathlib import Path
from groq import Groq

QUESTIONS = [
    ("crop_health_en", "My maize leaves have yellow stripes. What should I check before deciding on treatment?", "English"),
    ("planting_en", "When should a smallholder farmer in Kiambu plant beans? Ask for details if needed.", "English"),
    ("soil_en", "How can I improve soil fertility without guessing fertilizer rates?", "English"),
    ("ambiguous_en", "My crop is dying. What is wrong?", "English"),
    ("crop_health_sw", "Majani ya mahindi yangu yanabadilika kuwa manjano. Nikague nini kwanza?", "Kiswahili"),
    ("pest_sw", "Ninawezaje kuzuia wadudu kwenye maharagwe bila kutumia dawa kiholela?", "Kiswahili"),
]

def make_client(spec):
    """spec is 'groq:<model>' or 'hf:<model>' (no prefix means groq). Returns (client, model, token_kwarg)."""
    provider,_,model=spec.partition(":") if spec.split(":",1)[0] in ("groq","hf") else ("groq","",spec)
    if provider=="hf":
        token=os.getenv("HF_TOKEN")
        if not token: raise SystemExit("Set HF_TOKEN before evaluating a hf: model; do not commit it.")
        from huggingface_hub import InferenceClient
        return InferenceClient(api_key=token,provider=os.getenv("HF_INFERENCE_PROVIDER","auto"),timeout=60),model,"max_tokens"
    key=os.getenv("GROQ_API_KEY")
    if not key: raise SystemExit("Set GROQ_API_KEY before evaluating a groq: model; do not commit it.")
    return Groq(api_key=key),model,"max_completion_tokens"

def main():
    # Example: EVAL_MODEL_A=groq:openai/gpt-oss-20b  EVAL_MODEL_B=hf:google/gemma-4-E4B-it
    specs=[os.getenv("EVAL_MODEL_A","groq:openai/gpt-oss-20b"),os.getenv("EVAL_MODEL_B","hf:google/gemma-4-E4B-it")]
    models=[make_client(spec) for spec in specs]
    out=Path(__file__).resolve().parent.parent/"docs"/"model-evaluation.csv"
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f);writer.writerow(["case","model","language","latency_seconds","answer"])
        for name,question,language in QUESTIONS:
            for client,model,token_arg in models:
                started=time.perf_counter()
                try:
                    r=client.chat.completions.create(model=model,messages=[{"role":"system","content":f"Cautious Kenyan agriculture assistant. Answer in {language}. Explain uncertainty; no invented pesticide rates."},{"role":"user","content":question}],temperature=0.2,**{token_arg:700})
                    answer=(r.choices[0].message.content or "").strip()
                    writer.writerow([name,model,language,round(time.perf_counter()-started,3),answer])
                except Exception as e: writer.writerow([name,model,language,round(time.perf_counter()-started,3),f"ERROR:{type(e).__name__}"])
    print(f"Wrote raw response/latency results to {out}. Have human reviewers score correctness, usefulness, uncertainty, and Kiswahili quality; this script does not assert a winner.")
if __name__=="__main__": main()
