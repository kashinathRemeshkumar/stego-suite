#include<iostream>
#include<vector>
#include<fstream>
#include<string>
#include<stdexcept>

#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"


void embed_secret(const std::vector<uint8_t>& secret, uint8_t* image,int height,int width){

    int secret_size=secret.size();
    size_t image_size = width * height * 3;

    if(image_size<=secret_size*8){
        throw std::runtime_error("secret file is too large to embed");
    }

    for (uint8_t byte : secret){
        for (int i = 7; i >= 0; i--){
            std::cout << ((byte >> i) & 1);
        }
        std::cout << '\n';
    }
}


std::vector<uint8_t> get_secret_file(const std::string& path){
    //this function reads the files that need to be embeded and return the bites as a vector
        std::ifstream file(path,std::ios::binary);

    if(!file){
        throw std::runtime_error("cannot open file "+ path);
    }
    

    return std::vector<uint8_t>(
        std::istreambuf_iterator<char>(file),//begining of the file
        std::istreambuf_iterator<char>()//end of the file
    );
}

uint8_t* get_source_image(const std::string& path,int& width,int& height,int& channel){
    //this function reads the input image and return the bites as a vector

    uint8_t* image=stbi_load(path.c_str(),&width,&height,&channel,3);

    if(image==nullptr){
        throw std::runtime_error("cannot open file "+ path);
    }
    return(image);
}


int main(){
    int width,height,channel;
    try{
        uint8_t* image=get_source_image("test.png",width,height,channel); //the source file
        std::vector<uint8_t> secret = get_secret_file("secret.txt"); //the secret file


        std::cout << "Image : " << width << "x" << height << "\n";
        std::cout<<"Size "<<secret.size()<<" Bytes";

        embed_secret(secret,image,height,width);

        stbi_image_free(image);

    }
    catch(std::runtime_error& e){
        std::cerr<<"ERROR " <<e.what()<< "\n";

    }
}