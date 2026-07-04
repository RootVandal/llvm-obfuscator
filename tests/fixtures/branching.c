int add_or_sub(int a, int b) {
    if (a > b) {
        return a + b;
    } else {
        return a - b;
    }
}

int main() {
    int x = add_or_sub(3, 4);
    int y = add_or_sub(10, 2);
    return x + y;
}
