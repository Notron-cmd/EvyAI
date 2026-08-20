#include <stdio.h>

int main() {
    char nama[50];
    
    printf("Halo! Siapa nama kamu? ");
    scanf("%s", nama);
    
    printf("\nHalo %s, semangat ya belajar C-nya! hehe\n", nama);
    
    return 0;
}