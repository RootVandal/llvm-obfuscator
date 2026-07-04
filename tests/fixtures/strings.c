int puts(const char *s);

int main() {
    int x = 3 + 4;
    if (x > 5) {
        puts("big");
    } else {
        puts("small");
    }
    puts("done");
    return x;
}
