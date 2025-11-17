# TextObserver Integration with Batch Processing

## Overview

The `TextObserver` allows you to provide text-based input to GUM, which is then processed through the batch processing system to generate propositions. This is complementary to the `Screen` observer which analyzes screenshots.

## Key Improvements Made

### 1. Fixed TextObserver Implementation
The original `TextObserver` had several critical bugs:
- **Missing `self` parameter**: The `_worker()` method was missing `self`
- **Wrong attribute name**: Used `context` instead of `content` in the Update schema
- **Incomplete stop method**: The `stop()` method was missing `self` parameter and not properly cleaning up

**Solution**: Fixed all method signatures, corrected the Update schema usage, and added proper cleanup in the `stop()` method.

### 2. Updated Module Exports
- Fixed the observers `__init__.py` to properly export `TextObserver` (was exporting `Text` which didn't exist)

### 3. CLI Support for Text Input
- Added `--text-input` flag to enable text-based input mode via CLI
- Interactive mode allows users to enter text observations and see them batched in real-time
- Fixed argument parser syntax error in the CLI

### 4. Batch Processing Integration
The TextObserver fully integrates with the existing batch processing system:

```
TextObserver (input) 
    ↓
Observer.update_queue 
    ↓
GUM._default_handler 
    ↓
ObservationBatcher (queue-based batching) 
    ↓
GUM._batch_processing_loop (waits for batch ready)
    ↓
GUM._process_batch (combines observations, generates propositions)
```

## How It Works

### Batch Processing Flow

1. **Input**: Text is added via `observer.add_text(text)`
2. **Update Queue**: TextObserver converts text to `Update` objects and puts them in `update_queue`
3. **Batching**: Default handler pushes observations to persistent `ObservationBatcher`
4. **Batch Ready**: When `queue.size() >= min_batch_size`, batch processing is triggered
5. **Processing**: Combined text observations are sent to the LLM to generate propositions
6. **Filtering**: Generated propositions are filtered (identical, similar, different)
7. **Storage**: Propositions are stored with relationships to observations

### Key Configuration Parameters

```python
gum(
    user_name="user",
    model="gpt-4o-mini",
    observer,
    min_batch_size=5,      # Minimum observations before processing batch
    max_batch_size=50,     # Maximum observations per batch
)
```

## Usage

### Method 1: Interactive CLI Mode

```bash
python -m gum.cli -u myuser -m gpt-4o-mini --text-input \
    --min-batch-size 2 --max-batch-size 5
```

Then enter text observations:
```
> User spent 2 hours on coding
Added to batch (queue size: 1)
> User attended 3 meetings
Added to batch (queue size: 2)
# Batch automatically processes when min_batch_size is reached
```

### Method 2: Programmatic Usage

```python
import asyncio
from gum import gum
from gum.observers import TextObserver

async def main():
    observer = TextObserver()
    
    async with gum(
        user_name="myuser",
        model="gpt-4o-mini",
        observer,
        min_batch_size=3,
        max_batch_size=10
    ) as gum_instance:
        # Add text observations
        await observer.add_text("User opened 15 browser tabs")
        await observer.add_text("User worked for 3 hours without break")
        await observer.add_text("User made 5 code commits")
        
        # Wait for batch processing
        await asyncio.sleep(2)
        
        # Query results
        props = await gum_instance.recent(limit=5)
        for prop in props:
            print(f"Proposition: {prop.text}")
            print(f"Reasoning: {prop.reasoning}")

asyncio.run(main())
```

### Method 3: Combining Multiple Observers

```python
from gum.observers import Screen, TextObserver

observer_screen = Screen(model="gpt-4o-mini")
observer_text = TextObserver()

async with gum(
    user_name="myuser",
    model="gpt-4o-mini",
    observer_screen,
    observer_text,
    min_batch_size=5,
    max_batch_size=20
) as gum_instance:
    # Both screen and text observations are batched together
    await observer_text.add_text("User is coding")
    # Screen observer captures screenshots simultaneously
```

## Data Flow Example

### Input
```
Text Observer Input:
1. "User completed project A"
2. "User reviewed team's code"
3. "User mentored junior developer"
```

### Batching
```
ObservationBatcher State:
Queue: [obs1, obs2, obs3]
Size: 3 (>= min_batch_size of 2)
→ Batch Ready Event Triggered
```

### Processing
```
Combined Content:
[TextObserver] User completed project A
[TextObserver] User reviewed team's code
[TextObserver] User mentored junior developer

LLM Analysis → Generated Propositions:
1. "User is productive and makes consistent progress"
2. "User has mentorship responsibilities and expertise"
3. "User collaborates with team members"
```

### Storage
```
Propositions created with:
- proposition_id: auto-incremented ID
- text: proposition text
- reasoning: why it was generated
- observations: [obs1, obs2, obs3] (linked)
- version: 1
- revision_group: UUID
```

## Query and Retrieval

Once propositions are generated, you can query them:

```python
# BM25 Full-Text Search
results = await gum_instance.query(
    "project completion and mentorship",
    limit=5
)
for prop, score in results:
    print(f"Score: {score:.3f} - {prop.text}")

# Get Recent Propositions
recent = await gum_instance.recent(limit=10)

# With Observations
props_with_obs = await gum_instance.recent(
    limit=5,
    include_observations=True
)
for prop in props_with_obs:
    print(f"Proposition: {prop.text}")
    print(f"Based on {len(prop.observations)} observations")
```

## Batch Processing Advantages

1. **Cost Efficiency**: Combine 5-50 observations into a single LLM call instead of individual calls
2. **Performance**: Process multiple observations concurrently
3. **Context Awareness**: LLM sees all observations together, enabling better proposition generation
4. **Scalability**: Persistent queue with SQLite backend handles large volumes

### Performance Metrics

- **Without Batching**: 100 observations = 100 API calls
- **With Batching (max=10)**: 100 observations = 10 API calls (90% cost reduction)

## Configuration Examples

### Development (Frequent Small Batches)
```python
gum(..., min_batch_size=2, max_batch_size=5)
```

### Production (Large Batches)
```python
gum(..., min_batch_size=20, max_batch_size=100)
```

### Real-time Processing
```python
gum(..., min_batch_size=1, max_batch_size=1)  # Process immediately
```

## Troubleshooting

### Queue Not Processing
- Check `gum_instance.batcher.size()` to see queue size
- Verify `min_batch_size` is reached before processing triggers
- Ensure `await asyncio.sleep()` is used to allow async processing

### TextObserver Not Receiving Input
- Verify TextObserver is passed to gum constructor
- Check that updates are in the update_queue: `observer.update_queue.qsize()`
- Ensure proper `await` on `add_text()` calls

### Propositions Not Generated
- Check database connection: `await gum_instance.connect_db()`
- Verify API key is set (GUM_LM_API_KEY or OPENAI_API_KEY)
- Check logs for LLM API errors
- Ensure batch processing loop is running

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  TextObserver                            │
│  ┌─────────────────────────────────────────────────────┐│
│  │  _input_queue (asyncio.Queue)                       ││
│  │  _worker() - reads from _input_queue               ││
│  │  add_text(text) - user API                          ││
│  └─────────────────────────────────────────────────────┘│
│           │                                              │
│           ↓ emits Update(content, "input_text")         │
├─────────────────────────────────────────────────────────┤
│             update_queue (asyncio.Queue)                │
├─────────────────────────────────────────────────────────┤
│                  GUM._update_loop()                      │
│  Waits on observer.update_queue.get()                  │
│           │                                              │
│           ↓ calls _default_handler(observer, update)    │
├─────────────────────────────────────────────────────────┤
│            ObservationBatcher (persistent queue)        │
│  ┌─────────────────────────────────────────────────────┐│
│  │  SQLite Queue: persistqueue.Queue                   ││
│  │  push(observer_name, content, content_type)         ││
│  │  pop_batch(batch_size) - FIFO                       ││
│  │  should_process_batch() - min size check            ││
│  │  _batch_ready_event - signals batch ready           ││
│  └─────────────────────────────────────────────────────┘│
│           │                                              │
│           ↓ when size >= min_batch_size                 │
├─────────────────────────────────────────────────────────┤
│         GUM._batch_processing_loop()                    │
│  Waits on batcher.wait_for_batch_ready()              │
│           │                                              │
│           ↓ calls _process_batch(observations)          │
├─────────────────────────────────────────────────────────┤
│              Database Operations                        │
│  ┌─────────────────────────────────────────────────────┐│
│  │  1. Store Observation records                       ││
│  │  2. Generate propositions via LLM                   ││
│  │  3. Search for related propositions (BM25)          ││
│  │  4. Filter (identical/similar/different)            ││
│  │  5. Update/revise propositions                      ││
│  │  6. Link observations to propositions               ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

## Files Modified

1. **gum/observers/text.py** - Fixed implementation bugs
2. **gum/observers/__init__.py** - Fixed export name
3. **gum/cli.py** - Added text-input support and interactive mode
4. **examples/text_observer_batch_example.py** - Updated with comprehensive examples

## Next Steps

1. Run the example: `python examples/text_observer_batch_example.py`
2. Test interactive CLI: `python -m gum.cli -u test --text-input`
3. Integrate into your application with custom text sources
4. Monitor batch processing with logging: `logging.basicConfig(level=logging.DEBUG)`
