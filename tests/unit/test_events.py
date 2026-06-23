"""The feed must fan out, unsubscribe on disconnect, never block, and drain on close.

asyncio_mode=auto runs these async tests without a marker. The drop-oldest and
close()-sentinel behaviors are the load-bearing ones: they guarantee a slow reader
can't stall a publisher and that open SSE generators end on shutdown.
"""

import asyncio

from claudeplans.events import Event, EventFeed


async def test_publish_fans_out_to_two_subscribers() -> None:
    feed = EventFeed()
    received: list[list[Event]] = [[], []]

    async def consume(idx: int) -> None:
        with feed.subscribe() as sub:
            async for event in sub:
                received[idx].append(event)

    tasks = [asyncio.ensure_future(consume(i)) for i in range(2)]
    await asyncio.sleep(0)  # let both register their queues
    feed.publish(Event(key="k", rev="r1"))
    await asyncio.sleep(0)
    feed.close()
    await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert received == [[Event(key="k", rev="r1")], [Event(key="k", rev="r1")]]


async def test_subscribe_unregisters_on_disconnect() -> None:
    feed = EventFeed()

    async def consume() -> None:
        with feed.subscribe() as sub:
            async for _ in sub:
                pass

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0)
    assert len(feed._subscribers) == 1
    # A client disconnect cancels the awaiting iterator; the `with` block's __exit__
    # must unsubscribe as the cancellation unwinds the stack.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert len(feed._subscribers) == 0


async def test_bounded_drop_oldest_never_blocks() -> None:
    feed = EventFeed(maxsize=2)
    received: list[Event] = []
    gate = asyncio.Event()

    async def consume() -> None:
        with feed.subscribe() as sub:
            async for event in sub:
                await gate.wait()  # hold the reader so the queue overflows
                received.append(event)

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0)  # register the queue
    for i in range(5):
        feed.publish(Event(key="k", rev=f"r{i}"))  # must not block
    # First event is in-flight (already pulled by `await q.get()` before the gate);
    # the queue holds the newest two. Release the reader and let it drain, then close.
    gate.set()
    await asyncio.sleep(0)
    feed.close()
    await asyncio.wait_for(task, 1)
    # The oldest mid-events were dropped; the reader converges on the newest revs.
    assert Event(key="k", rev="r4") in received
    assert Event(key="k", rev="r0") not in received[1:]


async def test_close_terminates_active_subscribe_loop() -> None:
    feed = EventFeed()
    received: list[Event] = []

    async def consume() -> None:
        with feed.subscribe() as sub:
            async for event in sub:
                received.append(event)

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0)
    feed.publish(Event(key="k", rev="r1"))
    await asyncio.sleep(0)
    feed.close()
    await asyncio.wait_for(task, 1)
    assert received == [Event(key="k", rev="r1")]


async def test_publish_after_close_is_noop() -> None:
    feed = EventFeed()
    feed.close()
    feed.publish(Event(key="k", rev="r1"))  # must not raise
