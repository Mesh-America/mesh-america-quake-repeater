#pragma once
#include <stddef.h>
#include <stdint.h>
#include <math.h>
#include "variant.h"

#define HIGH 1
#define LOW 0
#define AR_INTERNAL_3_0 3

void digitalWrite(int pin, int level);
void analogReference(int reference);
void analogReadResolution(int bits);
int analogRead(int pin);
void delay(unsigned long milliseconds);
