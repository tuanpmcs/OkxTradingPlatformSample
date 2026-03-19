#include <benchmark/benchmark.h>

#include <cstdlib>

#ifndef HELLO_WORLD_BENCH_CMD
#define HELLO_WORLD_BENCH_CMD "./hello_world --bench-main > /dev/null 2>&1"
#endif

static void BM_MainStartup(benchmark::State& state)
{
    for (auto _ : state)
    {
        const int rc = std::system(HELLO_WORLD_BENCH_CMD);
        if (rc != 0)
        {
            state.SkipWithError("hello_world --bench-main failed");
            break;
        }
    }
}

BENCHMARK(BM_MainStartup)
    ->Unit(benchmark::kMillisecond)
    ->MinTime(0.5);

BENCHMARK_MAIN();
