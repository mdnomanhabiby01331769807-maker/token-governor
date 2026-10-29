# Contributing

## English

Thanks for helping. Please keep these rules:

- **No network access and no telemetry** in `scripts/tg.py`. A test enforces this.
- **Standard library only**, Python 3.9+.
- **Run the checks before you open a pull request:**
  ```bash
  python3 -m unittest discover -s tests -v
  python3 tools/validate_skill.py .
  ```
- **Claims need measurements.** A change that says it saves tokens must add or update a result under `evals/`.
- **Contract changes** (ledger format, stash format, CLI output, exit codes) need an issue first. Describe the old behaviour, the new behaviour, and how existing data migrates.
- **Keep `SKILL.md` short.** It must stay under 500 lines, ideally under about 40, because small tasks load it in full. Put long detail in `references/`, and say in `SKILL.md` when to read it.
- **Both languages.** User documents exist in English and Bangla (`README.md` and `README.bn.md`, and `docs/cost-and-benchmark.md` and `docs/cost-and-benchmark.bn.md`). When you change one, update the other, or open an issue asking for a translation.

The plugin API is not public yet. Propose it in an issue first.

## বাংলা

অবদানের জন্য ধন্যবাদ। এই নিয়মগুলো মেনে চলুন:

- `scripts/tg.py`-তে **কোনো নেটওয়ার্ক বা টেলিমেট্রি নেই।** একটি টেস্ট এটি যাচাই করে।
- **শুধু স্ট্যান্ডার্ড লাইব্রেরি**, Python 3.9+।
- পুল রিকোয়েস্টের আগে **চেকগুলো চালান:**
  ```bash
  python3 -m unittest discover -s tests -v
  python3 tools/validate_skill.py .
  ```
- **দাবির পেছনে মাপ লাগবে।** টোকেন সাশ্রয়ের দাবি করা পরিবর্তনে `evals/`-এর ফলাফল যোগ বা আপডেট করতে হবে।
- **কন্ট্রাক্ট বদলালে** (লেজার, স্ট্যাশ ফরম্যাট, CLI আউটপুট, exit code) আগে একটি ইস্যু খুলুন। পুরনো আচরণ, নতুন আচরণ, এবং পুরনো ডেটার মাইগ্রেশন লিখুন।
- **`SKILL.md` ছোট রাখুন।** এটি ৫০০ লাইনের নিচে থাকতে হবে, আদর্শভাবে ৪০-এর নিচে। ছোট কাজেও এজেন্ট পুরোটা লোড করে। বিস্তারিত লেখা `references/` ফোল্ডারে রাখুন, আর `SKILL.md`-তে লিখুন কখন পড়তে হবে।
- **দুই ভাষা।** ব্যবহারকারীর ডকুমেন্ট ইংরেজি ও বাংলায় আছে (`README.md` ও `README.bn.md`, এবং `docs/cost-and-benchmark.md` ও `docs/cost-and-benchmark.bn.md`)। একটি বদলালে অন্যটিও বদলান, অথবা অনুবাদের জন্য ইস্যু খুলুন।

প্লাগইন API এখনো পাবলিক নয়। প্রস্তাব থাকলে আগে ইস্যুতে লিখুন।
