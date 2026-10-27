#pragma once
#include <pthread.h>
#include <sched.h>
#include <errno.h>
static inline int edge_pthread_setaffinity(pthread_t thread, size_t size, const cpu_set_t *set) {
    if (!pthread_equal(thread, pthread_self())) return ENOTSUP;
    return sched_setaffinity(0, size, set) == 0 ? 0 : errno;
}
#define pthread_setaffinity_np edge_pthread_setaffinity
