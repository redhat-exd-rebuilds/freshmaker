=====================
Async Pyxis GQL Usage
=====================

In this page we will give some examples on how to use the asynchronous Pyxis GQL module
(``pyxis_gql_async.py``).

General remarks about asynchronous code
=======================================

To start, let's take a good analogy from Miguel Grinberg’s 2017 PyCon talk about how asynchronous
code works:

    Chess master Judit Polgár hosts a chess exhibition in which she plays multiple amateur players.
    She has two ways of conducting the exhibition: synchronously and asynchronously.

    Assumptions:
        - 24 opponents
        - Judit makes each chess move in 5 seconds
        - Opponents each take 55 seconds to make a move
        - Games average 30 pair-moves (60 moves total)

    *Synchronous version*: Judit plays one game at a time, never two at the same time, until the
    game is complete. Each game takes (55 + 5) * 30 == 1800 seconds, or 30 minutes. The entire
    exhibition takes 24 * 30 == 720 minutes, or 12 hours.

    *Asynchronous version*: Judit moves from table to table, making one move at each table. She
    leaves the table and lets the opponent make their next move during the wait time. One move
    on all 24 games takes Judit 24 * 5 == 120 seconds, or 2 minutes. The entire exhibition is now
    cut down to 120 * 30 == 3600 seconds, or just 1 hour. 

    Source: [RealPython]_ and [MiguelGrinberg]_

Therefore, async code can have a speedup in IO-bound scenarios by "freeing" the execution runtime
to do other things while a certain function waits for a response. This is different than
**parallellizing** and **threading**.

In async code, it is fundamental that the the functions that are being alternated are
**non-blocking**. Otherwise, the runtime will not be able to alternate between them.

When calling async functions, we have to create an **async loop**, which contains the
functions that will be alternated. In the analogy, this is similar to setting up the set of tables
and boards for the exhibition. The runtime will alternate between the functions in that context,
and then resume usual synchronous execution.

Consequently, async functions cannot be run directly, as the usual synchronous python functions
can. Instead, they need to be **awaited** inside some async loop. Python reserves a few special
keywords (``await``, ``async with``, ``async for``) to be used only inside asynchronous functions,
which are created with create ``async def``.

Finally, if you put only one function inside an async loop, you will make things work as if they
were synchronous, and therefore you will lose the async speedup. This would be analogous to
organizing an exhibition with just one board for Polgár -- it is a standard match.

If you have never used asynchronous code in python, references [RealPython]_ and [AsyncIO]_ are
good sources.


Usage examples
==============

Basic calls
-----------
Usually, when we write async code, we will rely on other async libraries that implement lower-level
functionality. Our code will then have to ``await`` the async functions of those libraries. For
example, we could await a ``get`` request made with ``aiohttp``:

.. code-block:: python
    :emphasize-lines: 3

    url = "https://docs.aiohttp.org/en/stable/index.html"
    async with aiohttp.ClientSession() as session:
        response = await session.get(url)

We can than make an async loop with ``asyncio.run``:

.. code-block:: python
    :emphasize-lines: 9

    async def main():
        url = "https://docs.aiohttp.org/en/stable/index.html"
        async with aiohttp.ClientSession() as session:
            response = await session.get(url)
        
        return response

    if __name__ == "__main__":
        response = asyncio.run(main())
        print(f"{response}")


Scheduling tasks and collecting results with ``gather``
-------------------------------------------------------
We can shedule a batch of tasks to run "together" (in the async sense) and then gather their results
with ``asyncio.create_task`` and ``asyncio.gather``:

.. code-block:: python 

    task1 = asyncio.create_task(async_function1(...))
    task2 = asyncio.create_task(async_function2(...))
    await asyncio.gather(task1, task2)

This is a simple option for when we just need to collect a set of results, without acting on each
of them separately.

If you have a variable number of tasks that need to be gathered, you could use a generator:

.. code-block:: python
    :emphasize-lines: 1

    async for obj in my_async_generator:
        task = asyncio.create_task(process_obj(obj))
        tasks.append(task)
    
    await asyncio.gather(*tasks)

The discussions in [AsyncFor]_ are very good to check.


Chaining results
----------------
If, on the other hand, you want to process each result as they become available, you can use
``asyncio.as_completed``. In this example, there are a few results that we want to ignore, so we
make a conditional aggregation after awaiting each execution:

.. code-block:: python 
    :emphasize-lines: 5

    x_values = [...]
    results_to_skip = [...]
    collected_results = []

    for f in asyncio.as_completed(
        [async_function(x) for x in x_values]
    ):
        result = await f
        if result not in results_to_skip:
            collected_results.append(result)        

Again, the discussions in [AsyncFor]_ are very good to check.


Usual structure of async code
-----------------------------
We will usually have the following elements when we use async code:

- lower level async functions that implement a given task
- async orchestrators, which create an async loop and aggregates several lower level async functions 
  (for example using ``asyncio.gather`` or ``async for``)
- a synchronous wrapper function, that calls the async orchestrator and integrates it in the context
  of the synchronous flow (for example with ``asyncio.run``)

It might be the case that a given module or package the latter two cases reside in 
externally-calling code. For the asynchronous Pyxis GQL module in Freshmaker
(``pyxis_gql_async.py``), this is precisely the case: the module itself provides the PyxisAsyncGQL
class with several async functions; it is up to the other modules that will use it
to build the async loop and aggregate those functions in them as needed.

Concrete example for using PyxisAsyncGQL
----------------------------------------
In this next example, we will call ``PyxisAsyncGQL.get_repository_by_path`` several times, each for
a given path and registry, and aggregate each result conditionally.

.. code-block:: python

    async def aggregate_paths():

        path_registry_vals:list[tuple[str, str]] = [...]
        results_to_skip = [...]
        collected_results = []

        for f in asyncio.as_completed(
            [PyxisAsyncGQL.get_repository_by_path(*x) for x in path_registry_vals]
        ):
            result = await f
            if result not in results_to_skip:
                collected_results.append(result)   

    def main():
        asyncio.run(aggregate_paths())


References
==========
.. [RealPython] https://realpython.com/async-io-python/
.. [MiguelGrinberg] https://youtu.be/iG6fr81xHKA?t=4m29s
.. [AsyncIO] https://docs.python.org/3/library/asyncio-task.html#
.. [AsyncFor] https://stackoverflow.com/questions/56161595/how-to-use-async-for-in-python
