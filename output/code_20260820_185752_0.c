#include <stdio.h>

int main() {
    int nilai = 85;
    
    if (nilai >= 80) {
        printf("Grade A\n");
    } else if (nilai >= 70) {
        printf("Grade B\n");
    } else {
        printf("Harus belajar lebih giat lagi!\n");
    }
    
    return 0;
}