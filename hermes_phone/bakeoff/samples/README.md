# Audio Samples for STT Bake-off

This directory holds recorded audio samples for offline STT benchmarking.

## Format

Each sample should consist of two files:
- `sample_name.wav` - Audio file (8kHz mu-law or 16kHz PCM recommended)
- `sample_name.txt` - Reference transcript in UTF-8

## Example

```
sample_01_booking.wav
sample_01_booking.txt  (contains: "أريد حجز طاولة لأربعة أشخاص")
```

## Usage

Place your sample files here, then run:

```bash
export DEEPGRAM_API_KEY=your_key_here
python -m hermes_phone.bakeoff.stt_benchmark
```

The benchmark compares Deepgram `ar-SA`, `ar-AE`, `ar`, and `multi` languages
on all samples and reports CER (Character Error Rate), WER (Word Error Rate),
and latency.

## Recommended Samples

For Phase 1 Bahraini Arabic testing:
1. Restaurant booking in Khaleeji dialect
2. Code-switching (Arabic/English mixed)
3. Venue names (Manama, Adliya, Seef, etc.)
4. Time expressions (Gulf Arabic format)
5. Phone number dictation (+973 format)

Samples to be provided by Mohamed before Phase 2.
